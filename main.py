"""TransAs — KivyMD entry point (Étape 3 UI).

Bootstraps:
  * A single :class:`DBManager` (path resolved to ``app.user_data_dir``
    on Android, ``<PROJECT_ROOT>/transas.db`` on desktop).
  * An :class:`OptimizeController`.
  * A ``ScreenManager`` hosting ``ImportScreen``, ``MainScreen`` and
    ``MapScreen``.

Run with::

    python main.py                # desktop dev
    buildozer android debug       # APK
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from kivy.lang import Builder
from kivy.uix.screenmanager import ScreenManager
from kivymd.app import MDApp

import config
from database.db_manager import DBManager
from ui.controllers.optimize_controller import OptimizeController
from ui.screens.import_screen import ImportScreen
from ui.screens.main_screen import MainScreen
from ui.screens.map_screen import MapScreen


# Inline KV — no separate ``transas.kv`` file needed. Empty id;
# we navigate via the loaded root widget through ``manager.current``.
_KV = """
#:kivy 2.3.0
ScreenManager:
"""


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


class TransAsApp(MDApp):
    """KivyMD application factory."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._db: Optional[DBManager] = None
        self._controller: Optional[OptimizeController] = None

    def build(self) -> ScreenManager:
        self.title = "TransAs"
        self.theme_cls.primary_palette = "Orange"
        self.theme_cls.theme_style = "Light"

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
        )

        writable = _writable_dir(self)
        db_path = writable / "transas.db"
        map_path = writable / "ui" / "_runtime_map.png"

        self._db = DBManager(db_path=str(db_path))
        self._controller = OptimizeController(db=self._db)

        manager = Builder.load_string(_KV)
        manager.add_widget(ImportScreen(db=self._db))
        manager.add_widget(MapScreen(db=self._db, map_output_path=map_path))
        manager.add_widget(MainScreen(db=self._db, controller=self._controller))
        manager.current = "import"
        return manager


if __name__ == "__main__":
    TransAsApp().run()
