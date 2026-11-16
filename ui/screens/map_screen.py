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

from kivy.uix.image import Image as KvImage
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDRaisedButton
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivy.metrics import dp

from database.db_manager import DBManager
# DEFERRED IMPORTS (defense-in-depth contre SIGSEGV Pillow, cf. BUG-001) :
#
# (1) ``ui.services.folium_renderer`` (qui pull ``PIL`` / Pillow's native
#     .so bindings — libjpeg, libpng, libwebp, libtiff, etc.). Sur Android
#     NDK r25c avec Pillow mal linké, l'import top-level peut déclencher un
#     SIGSEGV dans SDLThread pendant le bootstrap. Différer = confine le
#     load natif Pillow à une action user-initiée.
#
# (2) ``kivy.core.image.Image`` (alias ``CoreImage``) — le provider ``img_pil``
#     de Kivy AUTO-IMPORTE Pillow au module-load quand on importe
#     ``kivy.core.image``. C'est pourquoi on déferre aussi CoreImage. Sans
#     ça, le SIGSEGV arrive quand même au boot même si folium_renderer est
#     différé. Voir BUG-001 dans ``report_bug.md`` pour le diagnostic.
#
# Les deux imports sont faits localement dans ``refresh_from_db``.

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

        # BUG-010 mitigation (definitive): we NO LONGER create a KvImage here.
        # Even with ``opacity=0``, an Image widget whose ``texture`` is None at
        # construction time makes Kivy's canvas compiler emit empty VBO
        # instructions that crash inside ``kivy.graphics.compiler.so`` on the
        # Adreno 619 GLESv2 driver (Samsung SM-X210) — see ``report_bug.md``
        # BUG-010. We lazy-instantiate the Image ONLY when
        # ``refresh_from_db()`` has a valid PNG texture to assign. This
        # bypasses the VBO compile path entirely during app boot.
        self._image: Optional[KvImage] = None
        self._root_box = root

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
            # Do NOT touch self._image — it may be ``None`` if no render ever
            # succeeded (see BUG-010 lazy Image creation).
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
            # Do NOT touch self._image — see BUG-010 lazy Image creation.
            return

        ordered_indices = list(range(len(coords)))
        try:
            # Local import (defensive — see module-level note). Pulls in
            # Pillow native bindings only when the user actually requests
            # a map render, NOT at app startup.
            from ui.services.folium_renderer import render_route_bytes
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
            # DEFERRED CoreImage import (cf. note module-level) — le provider
            # ``img_pil`` de Kivy auto-importe PIL au module-load. Import
            # local = première utilisation de CoreImage = première
            # opportunité de SEGV (vs. au boot).
            from kivy.core.image import Image as CoreImage
            core_img = CoreImage(io.BytesIO(png_bytes), ext="png")
            # BUG-010 (definitive): lazy-create the Image widget only on the
            # FIRST successful PNG decode, and ONLY if it doesn't already
            # exist. We never expose an empty Image to Kivy's canvas compiler,
            # so we never hit the Adreno 619 VBO-complier-recursive SEGFAULT.
            # ``fit_mode="contain"`` replaces the deprecated Kivy 2.3.0
            # ``allow_stretch=True / keep_ratio=True`` and renders the
            # texture letterboxed inside the widget bounds when it finally
            # appears.
            if self._image is None:
                self._image = KvImage(
                    size_hint=(1, 1),
                    fit_mode="contain",
                )
                # Insert above the footer (which is always the last child of
                # ``self._root_box``). The summary label stays at index 0.
                self._root_box.add_widget(
                    self._image,
                    index=len(self._root_box.children) - 1,
                )
            self._image.texture = core_img.texture
        except Exception as exc:
            _logger.exception("CoreImage decode failed")
            self._summary_label.text = f"Décodage PNG impossible : {exc}"
            return

        self._summary_label.text = (
            f"Tournée du jour · {len(coords)} stops · ordre optimisé"
        )

    def _go_back(self) -> None:
        if self.manager:
            self.manager.current = "main"
