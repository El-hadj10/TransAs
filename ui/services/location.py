"""One-shot device position for the "RÉOPTIMISER D'ICI" action.

Design constraints (delivery-driver reality):

* **No continuous tracking, no background service.** One button press asks
  the system for at most one fresh fix, then falls back to the most recent
  cached fix (``getLastKnownLocation``) when the GPS has not answered yet.
* **Never blocks the UI thread.** The blocking Java calls run on a short-lived
  Python thread; the result is always delivered on the Kivy main thread.
* **Never raises at the UI.** Off-device (desktop/tests), on a device without
  Google Play services, or when the permission is refused, the caller gets
  ``None`` plus a human-readable reason and keeps its manual "Départ" field.
* **Permission is requested on first use only** (``ACCESS_FINE_LOCATION`` with
  ``ACCESS_COARSE_LOCATION`` as an accepted subset): Android 12+ lets the
  driver answer "approximate", which is precise enough to reorder a tour.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional, Sequence, Tuple

_logger = logging.getLogger("transas.ui.location")

FINE = "android.permission.ACCESS_FINE_LOCATION"
COARSE = "android.permission.ACCESS_COARSE_LOCATION"

# A cached fix older than this is not a usable "I am here" answer.
MAX_FIX_AGE_MS = 10 * 60 * 1000
# How long a single-update request may wait before we settle for a cached fix.
FIX_TIMEOUT_SEC = 12.0
# Read order: GPS first, then the fused/network cache, then passive.
PROVIDERS = ("gps", "network", "passive")
FRESH_PROVIDERS = ("gps", "network")

Position = Tuple[float, float]
PositionCallback = Callable[[Optional[Position], Optional[str]], None]
PermissionCallback = Callable[[bool], None]


# ---------------------------------------------------------------------------
# Platform helpers
# ---------------------------------------------------------------------------

def _is_android() -> bool:
    """Kivy's platform marker — CPython also reports ``linux`` on Android."""
    try:
        from kivy.utils import platform
        return platform == "android"
    except Exception:
        return False


def _autoclass(name: str):
    """Indirection so tests can supply a fake Java class registry."""
    from jnius import autoclass  # type: ignore[import-not-found]
    return autoclass(name)


def _post(fn: Callable[[], None]) -> None:
    """Run ``fn`` on the Kivy main thread (direct call when headless)."""
    try:
        from kivy.clock import Clock
        Clock.schedule_once(lambda _dt: fn(), 0)
        return
    except Exception:
        pass
    fn()


def _now_ms() -> int:
    try:
        return int(_autoclass("java.lang.System").currentTimeMillis())
    except Exception:
        return int(time.time() * 1000)


def _location_manager():
    Context = _autoclass("android.content.Context")
    PythonActivity = _autoclass("org.kivy.android.PythonActivity")
    manager = PythonActivity.mActivity.getSystemService(Context.LOCATION_SERVICE)
    if manager is None:
        raise RuntimeError("LocationManager unavailable")
    return manager


# ---------------------------------------------------------------------------
# Pure selection logic (unit-tested without Android)
# ---------------------------------------------------------------------------

def _pick_fix(candidates: Sequence[Sequence], *, now_ms: int,
              max_age_ms: int = MAX_FIX_AGE_MS) -> Optional[Position]:
    """Return the freshest ``(time_ms, lat, lon)`` candidate that is recent enough.

    ``max_age_ms <= 0`` disables the age filter (used for a fix we just
    received).  Malformed entries are skipped instead of raising: a broken
    provider must not break the whole re-optimise action.
    """
    usable = []
    for entry in candidates:
        if not entry or len(entry) < 3:
            continue
        stamp, lat, lon = entry[0], entry[1], entry[2]
        if stamp is None or lat is None or lon is None:
            continue
        stamp = int(stamp)
        if max_age_ms > 0 and now_ms - stamp > max_age_ms:
            continue
        usable.append((stamp, float(lat), float(lon)))
    if not usable:
        return None
    _, lat, lon = max(usable, key=lambda item: item[0])
    return (lat, lon)


# ---------------------------------------------------------------------------
# Permission bridge
# ---------------------------------------------------------------------------

def has_permission() -> bool:
    """True when a location permission is already granted."""
    if not _is_android():
        return False
    try:
        from android.permissions import check_permission  # type: ignore[import-not-found]
        return bool(check_permission(FINE) or check_permission(COARSE))
    except Exception:
        _logger.exception("location: check_permission failed")
        return False


def request_permission(callback: PermissionCallback) -> bool:
    """Ask for the location permission; ``callback(granted)`` on the Kivy thread.

    Returns ``False`` when the Android bridge is unavailable (desktop, test
    runner), so the screen can immediately fall back to the manual field.
    """
    if not _is_android():
        return False
    try:
        from android.permissions import request_permissions  # type: ignore[import-not-found]
    except Exception:
        _logger.exception("location: android.permissions unavailable")
        return False

    def _on_result(_permissions, grants) -> None:
        # Android 12+: [FINE, COARSE] where only COARSE may be granted when the
        # driver chooses "approximate". Either answer is usable for routing.
        granted = any(bool(grant) for grant in (grants or []))
        _post(lambda: callback(granted))

    try:
        request_permissions([FINE, COARSE], _on_result)
        return True
    except Exception:
        _logger.exception("location: request_permissions failed")
        return False


# ---------------------------------------------------------------------------
# Fix acquisition
# ---------------------------------------------------------------------------

def _best_known_fix(max_age_ms: int = MAX_FIX_AGE_MS) -> Optional[Position]:
    """Freshest cached fix across providers, or ``None`` if all are stale."""
    try:
        manager = _location_manager()
    except Exception:
        _logger.exception("location: LocationManager unavailable")
        return None
    candidates = []
    for name in PROVIDERS:
        try:
            if not manager.isProviderEnabled(name):
                continue
            location = manager.getLastKnownLocation(name)
        except Exception:
            continue
        if location is None:
            continue
        try:
            candidates.append((
                location.getTime(),
                location.getLatitude(),
                location.getLongitude(),
            ))
        except Exception:
            continue
    return _pick_fix(candidates, now_ms=_now_ms(), max_age_ms=max_age_ms)


def _request_fresh_fix(timeout_sec: float = FIX_TIMEOUT_SEC) -> Optional[Position]:
    """Wait up to ``timeout_sec`` for one fresh location update.

    ``requestSingleUpdate`` is deprecated since API 30 but still present in
    API 34; every failure path is caught because a missing fix is a normal
    outcome (indoors, GPS off, OEM restriction) and must stay non-fatal.
    """
    try:
        from jnius import PythonJavaClass, java_method  # type: ignore[import-not-found]
        manager = _location_manager()
        Looper = _autoclass("android.os.Looper")
    except Exception:
        _logger.exception("location: fresh fix bridge unavailable")
        return None

    received = threading.Event()

    class _Listener(PythonJavaClass):
        __javainterfaces__ = ["android/location/LocationListener"]
        __javacontext__ = "app"

        def __init__(self):
            super().__init__()
            self.location = None

        @java_method("(Landroid/location/Location;)V")
        def onLocationChanged(self, location):
            self.location = location
            received.set()

        @java_method("(ILjava/lang/String;Landroid/os/Bundle;)V")
        def onStatusChanged(self, provider, status, extras):
            pass

        @java_method("(Ljava/lang/String;)V")
        def onProviderEnabled(self, provider):
            pass

        @java_method("(Ljava/lang/String;)V")
        def onProviderDisabled(self, provider):
            pass

    listener = _Listener()
    requested = 0
    for name in FRESH_PROVIDERS:
        try:
            if not manager.isProviderEnabled(name):
                continue
            manager.requestSingleUpdate(name, listener, Looper.getMainLooper())
            requested += 1
        except Exception:
            _logger.exception("location: requestSingleUpdate(%s) failed", name)
    if requested == 0:
        return None
    try:
        received.wait(timeout_sec)
    finally:
        try:
            manager.removeUpdates(listener)
        except Exception:
            pass
    location = listener.location
    if location is None:
        return None
    try:
        candidate = (
            location.getTime(),
            location.getLatitude(),
            location.getLongitude(),
        )
    except Exception:
        return None
    return _pick_fix([candidate], now_ms=_now_ms())


def request_position(callback: PositionCallback, *,
                     timeout_sec: float = FIX_TIMEOUT_SEC) -> bool:
    """Acquire one position, then call ``callback(position, error_message)``.

    Returns ``False`` when no acquisition could even be started (not Android,
    permission missing, bridge broken); the callback is still invoked with a
    reason so the screen always ends up with a visible status message.
    """
    if not _is_android():
        _post(lambda: callback(None, "Localisation disponible uniquement sur Android"))
        return False
    if not has_permission():
        _post(lambda: callback(None, "Autorisation de localisation requise"))
        return False

    def _work() -> None:
        try:
            position = _request_fresh_fix(timeout_sec) or _best_known_fix()
        except Exception:
            _logger.exception("location: position acquisition crashed")
            position = None
        if position is None:
            _post(lambda: callback(
                None,
                "Position introuvable — vérifie que la localisation est active",
            ))
        else:
            _post(lambda: callback(position, None))

    threading.Thread(
        target=_work, name="transas.location", daemon=True,
    ).start()
    return True
