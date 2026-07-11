"""MapScreen — offline static PNG of the optimised tour.

Why ``kivy.core.image.Image`` and not ``AsyncImage`` or ``str(BytesIO(...))``:
AsyncImage probes the network before falling back to filesystem, which
adds hundreds of ms of latency per refresh on Android. Setting
``image.source = str(io.BytesIO(...))`` is invalid: the loader receives
the string representation of the BytesIO object and silently fails,
leaving ``image.texture`` as ``None`` — the screen renders blank.

The robust pattern is to decode once on the main thread via
``kivy.core.image.Image`` and assign its texture directly. The on-disk
write (when ``map_output_path`` is provided) remains a pass-through for
orientation changes that re-create the Image widget.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import List, Optional

from kivy.core.image import Image as CoreImage
from kivy.uix.image import Image as KvImage
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDRaisedButton
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivy.metrics import dp

from database.db_manager import DBManager
from ui.services.folium_renderer import render_route_bytes

_logger = logging.getLogger("transas.ui.map_screen")


class MapScreen(MDScreen):
    """Static map (PNG bytes) + summary KPIs of the today's tour."""

    def __init__(
        self,
        db: DBManager,
        map_output_path: Optional[Path] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.name = "map"
        self._db = db
        self._map_output_path = map_output_path

        root = MDBoxLayout(
            orientation="vertical",
            padding=dp(8),
            spacing=dp(8),
        )

        self._summary_label = MDLabel(
            text="Aucune tournée chargée",
            theme_text_color="Primary",
            font_style="Subtitle1",
            padding=(dp(8), dp(8)),
        )
        root.add_widget(self._summary_label)

        self._image = KvImage(
            size_hint=(1, 1),
            allow_stretch=True,
            keep_ratio=True,
        )
        root.add_widget(self._image)

        footer = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(12),
            adaptive_height=True,
            padding=dp(8),
        )
        footer.add_widget(MDRaisedButton(
            text="← Retour",
            on_release=lambda _b: self._go_back(),
        ))
        footer.add_widget(MDRaisedButton(
            text="Actualiser",
            on_release=lambda _b: self.refresh_from_db(),
        ))
        root.add_widget(footer)

        self.add_widget(root)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def refresh_from_db(self) -> None:
        coords: List[tuple] = []
        tour_today = self._db.load_today_tour()
        if tour_today is None or not tour_today.ordered_indices:
            self._summary_label.text = "Aucune tournée aujourd'hui"
            self._image.texture = None
            return

        for parcel_id in tour_today.ordered_indices:
            parcel = self._db.get_parcel(parcel_id)
            if parcel is None or parcel.coords is None:
                continue
            coords.append((parcel.lat, parcel.lon))

        if not coords:
            self._summary_label.text = (
                "Tournée enregistrée mais aucun colis géocodé"
            )
            self._image.texture = None
            return

        ordered_indices = list(range(len(coords)))
        try:
            png_bytes = render_route_bytes(coords, ordered_indices)
        except Exception as exc:
            _logger.exception("Map render failed")
            self._summary_label.text = f"Erreur de rendu : {exc}"
            return

        # Optional disk write (atomic via .tmp + replace so any orientation
        # change reload finds the file even if the previous process was
        # killed mid-rename).
        if self._map_output_path is not None:
            self._map_output_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._map_output_path.with_suffix(self._map_output_path.suffix + ".tmp")
            tmp.write_bytes(png_bytes)
            tmp.replace(self._map_output_path)

        # CRITICAL: assign the texture directly — never use
        # ``self._image.source = str(io.BytesIO(png_bytes))`` (Kivy treats
        # that as a filesystem path and silently misses).
        try:
            core_img = CoreImage(io.BytesIO(png_bytes), ext="png")
            self._image.texture = core_img.texture
        except Exception as exc:
            _logger.exception("CoreImage decode failed")
            self._summary_label.text = f"Décodage PNG impossible : {exc}"
            self._image.texture = None
            return

        self._summary_label.text = (
            f"Tournée du jour · {len(coords)} stops · ordre optimisé"
        )

    def _go_back(self) -> None:
        if self.manager:
            self.manager.current = "main"
