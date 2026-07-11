"""MainScreen — ordered parcels list with per-row Deliver + Optimize CTA.

Layout contract: every widget we ``add_widget`` to ``self._list_box``
(a vertical MDBoxLayout) uses ``index=len(self.children)`` so the new
widget sits at the END of the children list. With Kivy's standard
"first inserted at TOP" rule for vertical BoxLayout, this gives us a
deterministic top-to-bottom visual order matching our insertion order:

    [route_overview]   ← children[0] (TOP)
    [Optimize / + Add]
    [progress label]
    [parcel card 1]    ← …
    [parcel card 2]
    […]

Using ``add_widget(thing)`` with the default ``index=0`` would shove the
new widget to the top instead, stacking cards ABOVE the header.
"""
from __future__ import annotations

import logging
import sys
import webbrowser

from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDRaisedButton
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.scrollview import MDScrollView
from kivy.metrics import dp

from database.db_manager import DBManager
from ui.components.parcel_card import build_parcel_card
from ui.components.route_overview import build_route_overview
from ui.controllers.optimize_controller import (
    OptimizeController, OptimizeResult, ParcelInput,
)
from ui.services.uri_utils import (
    build_geo_uri, build_google_maps_web_url, coords_label,
)

_logger = logging.getLogger("transas.ui.main_screen")


def _append(box: MDBoxLayout, widget) -> None:
    """Append at the END of children (BOTTOM of the vertical layout).

    BoxLayout positions first-inserted at TOP, so the next insertion at
    ``len(children)`` ends up directly below the last.
    """
    box.add_widget(widget, index=len(box.children))


class MainScreen(MDScreen):
    """Today's tour: ordered cards + Optimize-now action."""

    # Stable children of the list box that we always keep at the TOP.
    # 0: route_overview header
    # 1: action row (Optimize / +Add)
    # 2: progress label
    _STABLE_HEADER_COUNT = 3

    def __init__(
        self,
        db: DBManager,
        controller: OptimizeController,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.name = "main"
        self._db = db
        self._controller = controller

        self._scroll = MDScrollView()
        self._list_box = MDBoxLayout(
            orientation="vertical",
            padding=dp(12),
            spacing=dp(8),
            adaptive_height=True,
        )
        self._scroll.add_widget(self._list_box)
        self._build_header()
        self.add_widget(self._scroll)

        self._controller.bind(
            progress_cb=lambda done, total, label: self._on_progress(done, total, label),
            finished_cb=lambda r: self._on_finished(r),
            error_cb=lambda exc: self._on_error(exc),
        )
        self.refresh_from_db()

    # ------------------------------------------------------------------
    # Layout helpers
    # ------------------------------------------------------------------

    def _build_header(self) -> None:
        # Insertion order matches the desired visual top-to-bottom order.
        _append(self._list_box, build_route_overview(
            stops_count=0, total_km=None, mode="—",
        ))
        action_row = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(12),
            adaptive_height=True,
            padding=(dp(12), dp(4)),
        )
        self._optimize_btn = MDRaisedButton(
            text="Optimiser la tournée",
            on_release=lambda _b: self._kick_optimization(),
        )
        action_row.add_widget(self._optimize_btn)
        action_row.add_widget(MDRaisedButton(
            text="+ Ajouter",
            on_release=lambda _b: self._switch_to_import(),
        ))
        _append(self._list_box, action_row)

        self._progress_label = MDLabel(
            text="",
            theme_text_color="Hint",
            font_style="Caption",
            padding=(dp(12), 0),
        )
        _append(self._list_box, self._progress_label)

    # ------------------------------------------------------------------
    # Data refresh + actions
    # ------------------------------------------------------------------

    def refresh_from_db(self) -> None:
        """Rebuild the parcel card list from the database."""
        pending = self._db.list_pending()
        tour_today = self._db.load_today_tour()
        ordered_pending = self._order_by_tour(pending, tour_today)
        self._render_cards(ordered_pending)

    def _order_by_tour(self, pending, tour_today) -> list:
        if tour_today is None or not tour_today.ordered_indices:
            return pending
        order = tour_today.ordered_indices
        by_id = {p.id: p for p in pending}
        sorted_list: list = []
        for idx in order:
            if idx in by_id:
                sorted_list.append(by_id.pop(idx))
        sorted_list.extend(by_id.values())
        return sorted_list

    def _render_cards(self, ordered_pending) -> None:
        # Drop ALL existing children and rebuild from scratch (header +
        # action row + progress label + cards). Simple and correct
        # because the screen rebuilds infrequently (optimize finished,
        # back from import, deliver toggle).
        self._list_box.clear_widgets()
        self._build_header()  # re-add the 3 stable header widgets

        for i, parcel in enumerate(ordered_pending, start=1):
            coord_text = (
                coords_label(parcel.lat, parcel.lon) if parcel.coords
                else "(non géocodé)"
            )
            navigate_label = (
                (parcel.lat, parcel.lon, parcel.address)
                if i == 1 and parcel.coords is not None
                else None
            )
            card = build_parcel_card(
                order=i,
                address=parcel.address,
                coord_text=coord_text,
                eta_text="",
                status=parcel.status,
                parcel_id=parcel.id,
                on_delivered=self._on_delivered,
                on_navigate=self._launch_navigation,
                navigate_label=navigate_label,
                show_deliver_button=True,
            )
            _append(self._list_box, card)

    # ------------------------------------------------------------------
    # Controller callbacks (main thread, see Clock.schedule_once)
    # ------------------------------------------------------------------

    def _kick_optimization(self) -> None:
        if self._controller.is_running:
            self._progress_label.text = "Optimisation déjà en cours…"
            return
        pending = self._db.list_pending()
        inputs = [
            ParcelInput(id=p.id, address=p.address, lat=p.lat, lon=p.lon)
            for p in pending
        ]
        if not inputs:
            self._progress_label.text = "Aucun colis à optimiser."
            return
        self._optimize_btn.disabled = True
        try:
            self._controller.start_geocode_then_optimize(inputs)
        except RuntimeError as exc:
            self._optimize_btn.disabled = False
            self._progress_label.text = f"Erreur : {exc}"

    def _on_progress(self, done: int, total: int, label: str) -> None:
        # Stage + counter — UI sees both thanks to the (done, total, label)
        # callback signature widened in OptimizeController.
        self._progress_label.text = f"{label}  {done}/{total}"

    def _on_finished(self, result: OptimizeResult) -> None:
        self._optimize_btn.disabled = False
        self._progress_label.text = (
            f"Terminé · {result.matrix_source} · "
            f"{result.total_distance_m/1000:.1f} km"
        )
        self.refresh_from_db()

    def _on_error(self, exc: BaseException) -> None:
        self._optimize_btn.disabled = False
        self._progress_label.text = f"Erreur : {exc}"
        _logger.warning("Optimization error surfaced to UI: %s", exc)

    def _on_delivered(self, parcel_id: int) -> None:
        self._db.mark_delivered(parcel_id)
        self.refresh_from_db()

    def _switch_to_import(self) -> None:
        if self.manager:
            self.manager.current = "import"

    # ------------------------------------------------------------------
    # Out-of-app navigation (Android intent / webbrowser fallback)
    # ------------------------------------------------------------------

    def _launch_navigation(self, lat: float, lon: float, label: str) -> None:
        if sys.platform == "android" or _on_android_kivy():
            _fire_android_geo_intent(lat, lon, label)
            return
        try:
            webbrowser.open(build_google_maps_web_url(lat, lon))
            self._progress_label.text = "Ouverture du navigateur…"
        except Exception as exc:  # pragma: no cover - desktop only
            self._progress_label.text = f"Navigateur indisponible : {exc}"


def _on_android_kivy() -> bool:
    """Detect Kivy's platform bootstrap (vs CPython on host)."""
    try:
        from kivy.utils import platform
        return platform == "android"
    except Exception:
        return False


def _fire_android_geo_intent(lat: float, lon: float, label: str) -> None:
    """Fire an Android ``geo:`` URI intent via jnius (URL-encoded label)."""
    try:
        from jnius import autoclass  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - Android-only
        _logger.warning("jnius unavailable on this platform: %s", exc)
        webbrowser.open(build_google_maps_web_url(lat, lon))
        return
    try:
        Intent = autoclass("android.content.Intent")
        Uri = autoclass("android.net.Uri")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        intent = Intent(Intent.ACTION_VIEW)
        intent.setData(Uri.parse(build_geo_uri(lat, lon, label)))
        PythonActivity.mActivity.startActivity(intent)
    except Exception as exc:  # pragma: no cover - Android-only
        _logger.warning("Android intent failed: %s", exc)
        webbrowser.open(build_google_maps_web_url(lat, lon))
