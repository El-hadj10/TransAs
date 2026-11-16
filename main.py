"""TransAs — KivyMD entry point (Étape 3 UI).

Bootstraps:
  * A single :class:`DBManager` (path resolved to ``app.user_data_dir``
    on Android, ``<PROJECT_ROOT>/transas.db`` on desktop).
  * An :class:`OptimizeController`.
  * A :class:`SafeTransAsScreen` (Kivy primitives only — no KivyMD
    elevation/FBO instructions, see ``knowledge.md`` §
    "Lessons learned — dragon-bug awareness").

Run with::

    python main.py                # desktop dev
    buildozer android debug       # APK

Safety net: the APK md5 ``98730137c81b11c519909e39f40995a2`` is currently
shipped on the test device (cf. ``knowledge.md`` § "Safety net APK"). If a
new commit ever crashes on install, ``adb install -r`` that binary to roll
back.
"""
from __future__ import annotations

import os
import logging
import traceback
from pathlib import Path
from typing import Optional

# On Android, Kivy may default to a location that triggers PermissionError
# during bootstrap logo copy on some OEM builds. Pin KIVY_HOME explicitly
# before any Kivy import.
_android_argument = os.environ.get("ANDROID_ARGUMENT")
_android_private = os.environ.get("ANDROID_PRIVATE")
if _android_argument:
    os.environ["KIVY_NO_CONFIG"] = "1"
    os.environ["KIVY_HOME"] = str(Path(_android_argument) / ".kivy")
elif _android_private:
    os.environ["KIVY_NO_CONFIG"] = "1"
    os.environ["KIVY_HOME"] = str(Path(_android_private) / ".kivy")

# --- Cheap defensive measure (kept from the Adreno-era build) ---------------
# Disable multisampling BEFORE any Kivy import. Kivy's default is
# "2" which keeps MSAA enabled. On the Adreno 619/750 GLESv2 driver the
# MSAA VBO compile path was the reproducible trigger for SIGSEGV faults
# (cf. knowledge.md "🐉 Never try to fix...").
#
# Caveat: on Android p4a, ``Config`` is often already read by the time
# ``main.py`` executes (PythonActivity triggers SDL2 init before the
# Python script is loaded), so this ``set`` may silently no-op there.
# On desktop it is honoured. Either way the call is a cheap belt-and-
# braces measure that costs ~0 ms; keep it as a no-cost insurance.
try:
    from kivy.config import Config as _TransAsConfig
    _TransAsConfig.set('graphics', 'multisamples', '0')
except Exception:  # noqa: BLE001 — config not yet initialised is fine
    pass

from kivy.app import App

import config
from database.db_manager import DBManager
from ui.controllers.optimize_controller import OptimizeController
from ui.screens.safe_screen import SafeTransAsScreen


def _enable_soft_keyboard_panning() -> None:
    """Keep the field being typed in visible above the Android keyboard.

    Reported by El-hadj on 27/10/2026: the IME covered the form and the driver
    typed blind into "Ajouter une adresse". ``softinput_mode = 'below_target'``
    makes SDL pan the window so the focused :class:`TextInput` sits just above
    the keyboard. It is the only mode that works on SDL2/Android: ``resize``
    is documented as non-functional there and ``keyboard_height`` reports 0,
    so an app-level resize could not be computed either.
    """
    try:
        from kivy.utils import platform
        if platform != "android":
            return
        from kivy.core.window import Window

        Window.softinput_mode = "below_target"
    except Exception:  # noqa: BLE001 — cosmetic concern, never block startup
        logging.getLogger("transas.bootstrap").exception(
            "Window.softinput_mode could not be set",
        )


def _writable_dir(app) -> Path:
    """Pick a writable directory on the current platform.

    On Android Kivy bootstrap: ``app.user_data_dir`` (read-write).
    On desktop / unknown: ``PROJECT_ROOT`` (read-write in dev).
    """
    try:
        from kivy.utils import platform
    except Exception:
        platform = ""
    if platform == "android":
        try:
            return Path(app.user_data_dir)
        except Exception:
            pass
    return Path(config.Config.PROJECT_ROOT)


class TransAsApp(App):
    """KivyMD application factory."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._db: Optional[DBManager] = None
        self._controller: Optional[OptimizeController] = None

    def build(self) -> SafeTransAsScreen:
        self.title = "TransAs"
        _enable_soft_keyboard_panning()

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
        )
        # Kivy's default log mode attaches its handlers to the root logger and
        # sets ``logging.root`` to NOTSET (kivy/logger.py), so every DEBUG
        # record from urllib3/requests/PIL reaches logcat: the first boot on
        # the test tablet produced ~98k logcat lines in 40 s, one per tile
        # HTTP chunk. Pin the root level and quiet the chatty libraries;
        # Kivy's own ``[INFO   ]`` lines still come through.
        logging.getLogger().setLevel(logging.INFO)
        for _noisy in ("urllib3", "requests", "PIL"):
            logging.getLogger(_noisy).setLevel(logging.WARNING)

        writable = _writable_dir(self)
        db_path = writable / "transas.db"
        self._db = DBManager(db_path=str(db_path))
        self._controller = OptimizeController(db=self._db)
        return SafeTransAsScreen(db=self._db, controller=self._controller)


if __name__ == "__main__":
    # Bootstrap-time safety net: if a Python-level exception fires during
    # ``TransAsApp().run()`` (build(), screen init, etc.), the traceback
    # would otherwise vanish into the Kivy event loop with no logcat breadcrumb.
    # Catching here + logging via the standard ``logging`` module ensures the
    # ``transas.bootstrap`` logger emits the full traceback at CRITICAL level,
    # which p4a routes to logcat under the ``python`` tag. Note: this does NOT
    # catch native SIGSEGV (e.g. SDLThread/libSDL2 crashes) — those are out of
    # Python's reach and require a rebuild with the offending .so fixed.
    try:
        TransAsApp().run()
    except Exception:  # noqa: BLE001 — last-resort surface
        # Note: deliberately NOT catching BaseException (KeyboardInterrupt,
        # SystemExit, GeneratorExit) so Kivy's graceful shutdown on Ctrl-C
        # still works without going through our error logger.
        logging.getLogger("transas.bootstrap").critical(
            "FATAL BOOTSTRAP ERROR:\n%s", traceback.format_exc(),
        )
        raise
