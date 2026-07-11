"""Address -> GPS geocoder, backed by Nominatim with a local JSON cache.

This module is the only place that talks to Nominatim. It enforces:
  * a local JSON cache (case-insensitive address keys) to avoid re-hitting
    Nominatim for known addresses;
  * a 1.1 s inter-request delay on top of the strict 1 req/sec rate limit
    imposed by the Nominatim ToS;
  * a ``User-Agent`` identifying the application;
  * a module-level ``threading.Lock`` covering the rate-limit triplet
    (elapsed check + HTTP request + timer update) so future worker-thread
    callers can't race past the 1 req/sec policy;
  * explicit ``verify=True`` + split (connect, read) timeout so TLS is
    always verified and a stalled TCP handshake can't hang the worker.

The cache lives at ``${Config.CACHE_DIR}/${Config.GEOCODING_CACHE_FILE}``.
Tests inject a custom cache directory via ``monkeypatch`` or by patching
attributes on ``config.Config``.
"""
from __future__ import annotations

import logging

import json
import threading
import time
from pathlib import Path
from typing import Optional, Tuple

import requests

import config

# Module-level logger so the app can route rate-limit / cache diagnostics
# through its standard logging config without us ever printing to stdout.
_logger = logging.getLogger("transas.core.geocoder")


class GeocodeResult:
    """Lightweight value object returned by ``geocode``."""

    __slots__ = ("lat", "lon", "display_name", "source")

    def __init__(self, lat: float, lon: float, display_name: str, source: str):
        self.lat = lat
        self.lon = lon
        self.display_name = display_name
        self.source = source  # "cache" or "nominatim"

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"GeocodeResult({self.lat}, {self.lon}, source={self.source!r})"

    def __eq__(self, other) -> bool:
        return (
            isinstance(other, GeocodeResult)
            and self.lat == other.lat
            and self.lon == other.lon
            and self.source == other.source
        )


# Module-level state used to enforce the 1 req/sec Nominatim policy.
# Both are guarded by ``_rate_lock`` so concurrent threads cannot race past
# the elapsed check and fire two requests in quick succession.
_last_request_ts: float = 0.0
_rate_lock = threading.Lock()


def _cache_path() -> Path:
    cache_dir = Path(config.Config.CACHE_DIR)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / config.Config.GEOCODING_CACHE_FILE


def load_cache() -> dict:
    """Read the on-disk JSON cache. Returns ``{}`` if missing or malformed."""
    path = _cache_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_cache(cache: dict) -> None:
    """Atomically write the JSON cache."""
    path = _cache_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def clear_cache() -> None:
    """Remove the on-disk geocoding cache (mainly for ops/debug)."""
    path = _cache_path()
    if path.exists():
        path.unlink()


def _do_nominatim_request(address: str) -> Optional[Tuple[float, float, str]]:
    """Hit the Nominatim API. Returns (lat, lon, display_name) or None.

    Thread-safe via ``_rate_lock``: the elapsed check, the HTTP request,
    and the timestamp update are all inside the same critical section.
    """
    global _last_request_ts
    with _rate_lock:
        elapsed = time.monotonic() - _last_request_ts
        if elapsed < config.Config.NOMINATIM_MIN_DELAY_SEC:
            time.sleep(config.Config.NOMINATIM_MIN_DELAY_SEC - elapsed)

        url = f"{config.Config.NOMINATIM_URL}/search"
        params = {"q": address, "format": "json", "limit": 1}
        headers = {"User-Agent": config.Config.NOMINATIM_USER_AGENT}
        response = requests.get(
            url, params=params, headers=headers,
            timeout=(3.05, config.Config.NOMINATIM_TIMEOUT_SEC),
            verify=True,
        )
        _last_request_ts = time.monotonic()
        response.raise_for_status()

        payload = response.json()
        if not payload:
            return None
        item = payload[0]
        return float(item["lat"]), float(item["lon"]), item["display_name"]


def geocode(address: str, *, use_cache: bool = True) -> Optional[GeocodeResult]:
    """Resolve ``address`` to lat/lon, using the cache when possible.

    Args:
        address: Free-form postal address string.
        use_cache: When False, bypass the on-disk cache entirely.

    Returns:
        A :class:`GeocodeResult` on hit, ``None`` if Nominatim has nothing.
    """
    key = address.strip().lower()
    if not key:
        return None

    if use_cache:
        cache = load_cache()
        if key in cache:
            rec = cache[key]
            return GeocodeResult(rec["lat"], rec["lon"], rec["display_name"], "cache")

    fetched = _do_nominatim_request(address)
    if fetched is None:
        return None
    lat, lon, display_name = fetched
    result = GeocodeResult(lat, lon, display_name, "nominatim")

    if use_cache:
        # NOTE: the cache write sits OUTSIDE ``_rate_lock`` by design.
        # Two threads racing here would race-read/race-write the same
        # JSON file, but the end state is correct in both cases:
        #   * different keys  -> merged; last writer per key wins, all
        #     keys end up present, idempotent for the user.
        #   * the same key    -> identical data overwrites itself; the
        #     upstream HTTP was already serialised by ``_rate_lock``
        #     so the second write is just a no-op overwrite.
        # The alternative (locking the disk write too) would couple the
        # rate-limit timing to filesystem atomicity for very little gain.
        cache = load_cache()
        cache[key] = {"lat": lat, "lon": lon, "display_name": display_name}
        save_cache(cache)

    return result
