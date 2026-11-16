"""Adreno-safe route planner UI inspired by delivery-driver workflows.

The screen intentionally stays on Kivy primitives: no KivyMD elevation/FBO
instructions are created.  It provides the essential route-planner loop:
add stops, optimise, see the geographical order, then mark each stop done.
"""
from __future__ import annotations

import io
import logging
import math
import threading
from typing import Iterable

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import (
    Canvas, Color, Ellipse, Line, Rectangle,
    StencilPop, StencilPush, StencilUnUse, StencilUse,
)
from kivy.metrics import dp
from kivy.properties import BooleanProperty, ListProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.storage.jsonstore import JsonStore

from database.db_manager import DBManager
import config
from ui.controllers.optimize_controller import OptimizeController, OptimizeResult, ParcelInput
from ui.services.navigation import open_navigation
from ui.services.batch_import import parse_addresses
from ui.services.location import has_permission, request_permission, request_position
from ui.services.speech import request_address


NAVY = (0.04, 0.10, 0.19, 1)
PANEL = (0.08, 0.16, 0.28, 1)
ORANGE = (1.0, 0.49, 0.10, 1)
MINT = (0.20, 0.82, 0.62, 1)
WHITE = (0.95, 0.97, 1.0, 1)
MUTED = (0.63, 0.71, 0.82, 1)
DEFAULT_CITY = (48.8566, 2.3522)  # Paris center fallback

_logger = logging.getLogger("transas.ui.safe_screen")


class _Collapsible(BoxLayout):
    """A vertical block that can be folded away completely.

    Kivy has no visibility flag, and hiding a widget by giving it no height
    would still cost the parent's ``spacing`` gap. So the block carries its
    own top margin (``gap``) and the parent lays its children out with
    ``spacing=0``: collapsed, the block takes exactly no room at all.

    Colour is the second problem: a zero-height child still *paints* outside
    its box (that is how the map's zoom buttons sit over the map). Setting
    ``opacity`` folds the whole subtree away, since Kivy's canvas opacity is
    cumulative for children.
    """

    collapsed = BooleanProperty(False)

    def __init__(self, gap=0, **kwargs):
        super().__init__(orientation="vertical", size_hint_y=None, spacing=0, **kwargs)
        if gap:
            self.add_widget(BoxLayout(size_hint_y=None, height=gap))
        self.bind(minimum_height=self._sync_height, collapsed=self._sync_height)

    def _sync_height(self, *_args) -> None:
        if self.collapsed:
            self.height = 0
            self.opacity = 0
            self.disabled = True
        else:
            self.opacity = 1
            self.disabled = False
            self.height = self.minimum_height


class RouteMap(Widget):
    """Route canvas: real OSM basemap once fetched, Kivy-drawn route on top.

    Two layers, on purpose:

    * the basemap is a single stitched PNG used as **one** texture on **one**
      rectangle. That is the cheapest GPU path available on the Adreno
      target, where a pile of image instructions used to trip the VBO
      compiler (cf. BUG-010). It is fetched on a worker thread so the UI keeps
      running while the tiles arrive, and cached on disk so refreshing the
      same area costs nothing;
    * the route itself stays on Kivy primitives (Line/Ellipse), which keeps it
      visible even when no tile can be obtained. Off-line — or if the keyless
      tile service refuses the requests — the canvas falls back to the
      schematic grid it shipped with before, plus a caption saying why.

    Interaction: the view starts fitted to the tour. Two small buttons zoom in
    and out, and two fingers pinch-zoom and pan. A single-finger drag is
    deliberately **not** captured — the map is only ~170 dp tall inside a
    long form, and stealing vertical drags would make the form unscrollable.
    """

    stops = ListProperty([])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._basemap = None        # Kivy Texture of the stitched tiles
        self._core_image = None     # keeps the Texture's owner alive
        self._project = None        # (lat, lon) -> (fx, fy), both in 0..1
        self._render = None         # last MapRender (zoom, centre, unproject)
        self._wanted_key = None     # basemap the widget currently asks for
        self._size_event = None
        self._stops_key = None
        # Viewport: ``None`` = fitted to the tour, else ``(zoom, lat, lon)``
        # once the user zoomed or panned.
        self._view = None
        # Live gesture transform, painted on the texture already on screen for
        # instant feedback; folded into ``_view`` and re-rendered on release.
        self._live_scale = 1.0
        self._live_dx = 0.0
        self._live_dy = 0.0
        self._touches = {}
        self._pinch = None
        # Everything this widget paints lives in its own Canvas so a repaint
        # can clear it without touching the children's canvases: those are
        # added *to* the parent canvas by ``add_widget``, and clearing the
        # parent canvas used to take the zoom buttons down with it (they were
        # simply never drawn). A Canvas *is* an InstructionGroup, and unlike a
        # bare group it supports ``with`` — which is how the painting code
        # reads. It is added before the children, so the map still paints
        # underneath them.
        self._dynamic = Canvas()
        self.canvas.add(self._dynamic)
        self._hint = Label(
            text="", font_size="11sp", color=MUTED, halign="center",
            valign="middle", size_hint=(None, None), opacity=0,
        )
        self.add_widget(self._hint)
        self._zoom_in = self._zoom_button("+", 1)
        self._zoom_out = self._zoom_button("−", -1)
        self.add_widget(self._zoom_in)
        self.add_widget(self._zoom_out)
        self.bind(pos=self._redraw, size=self._on_size, stops=self._on_stops)
        self._redraw()
        # Deferred: at construction the widget has no size yet, so the first
        # request is made once the layout pass has given it one.
        Clock.schedule_once(lambda _dt: self._request_basemap(), 0)

    def _zoom_button(self, text: str, delta: int) -> Button:
        """One of the two on-map zoom controls (no key, no network of its own)."""
        button = Button(
            text=text,
            font_size="17sp",
            bold=True,
            color=WHITE,
            background_normal="",
            background_color=(0.12, 0.22, 0.35, 0.92),
            size_hint=(None, None),
            size=(dp(30), dp(30)),
            disabled=True,
        )
        button.bind(on_release=lambda _button, step=delta: self._zoom_by(step))
        return button

    def set_stops(self, stops: Iterable[tuple[float, float]]) -> None:
        self.stops = list(stops)

    # ------------------------------------------------------------------
    # Basemap acquisition (worker thread -> Clock)
    # ------------------------------------------------------------------

    def _on_stops(self, *_args) -> None:
        coords = tuple((round(lat, 5), round(lon, 5)) for lat, lon in self.stops)
        if coords != self._stops_key:
            # A different tour: back to the fitted view, user pan/zoom gone.
            self._stops_key = coords
            self._view = None
            self._reset_live()
        self._redraw()
        self._request_basemap()

    def _on_size(self, *_args) -> None:
        self._redraw()
        if self._size_event is not None:
            self._size_event.cancel()
        # Debounced: a layout pass fires several sizes in a row (rotation,
        # soft keyboard, scroll), and each render costs a tile round-trip.
        self._size_event = Clock.schedule_once(
            lambda _dt: self._request_basemap(), 0.4,
        )

    def _request_basemap(self) -> None:
        width, height = int(self.width), int(self.height)
        if width < dp(40) or height < dp(40):
            return
        view = self._view
        key = (
            tuple((round(lat, 5), round(lon, 5)) for lat, lon in self.stops),
            width,
            height,
            None if view is None else (view[0], round(view[1], 5), round(view[2], 5)),
        )
        if key == self._wanted_key:
            return
        self._wanted_key = key
        threading.Thread(
            target=self._render_basemap,
            args=(key, list(self.stops), width, height, view),
            name="transas.basemap",
            daemon=True,
        ).start()

    def _render_basemap(self, key, stops, width, height, view) -> None:
        """Worker side: no Kivy call except the scheduled hand-off."""
        result = None
        try:
            # Imported here (not at module level) so Pillow's native bindings
            # are loaded on first use rather than during bootstrap — BUG-001.
            from ui.services.tile_map import render_map

            if view is None:
                result = render_map(stops, width, height)
            else:
                result = render_map(
                    stops, width, height, zoom=view[0], center=(view[1], view[2]),
                )
        except Exception:
            _logger.exception("basemap render failed")
        Clock.schedule_once(lambda _dt: self._apply_basemap(key, result), 0)

    def _apply_basemap(self, key, result) -> None:
        """Main thread: turn the PNG into a texture and repaint."""
        if key != self._wanted_key:
            return  # superseded by a newer request
        if result is None:
            self._set_hint("Fond de carte indisponible\n(connexion ou service de tuiles)")
            return
        try:
            from kivy.core.image import Image as CoreImage

            core = CoreImage(io.BytesIO(result.png), ext="png")
            texture = core.texture
        except Exception:
            _logger.exception("basemap decode failed")
            self._set_hint("Fond de carte illisible.")
            return
        if texture is None:
            self._set_hint("Fond de carte vide.")
            return
        self._basemap = texture
        self._core_image = core
        self._render = result
        self._project = result.project
        self._reset_live()
        self._set_hint("")
        self._redraw()

    # ------------------------------------------------------------------
    # Gestures — two fingers (pinch/pan); one finger stays with the page
    # ------------------------------------------------------------------

    def on_touch_down(self, touch):
        if super().on_touch_down(touch):
            return True  # a zoom button took it
        if self._render is None or not self.collide_point(*touch.pos):
            return False
        self._touches[touch.uid] = touch
        if len(self._touches) < 2:
            # Not ours yet: this finger may well be a page scroll.
            return False
        self._pinch = {
            "distance": self._finger_distance(),
            "mid": self._finger_mid(),
        }
        for held in self._touches.values():
            held.grab(self)
        return True

    def on_touch_move(self, touch):
        if touch.uid not in self._touches:
            return False
        if self._pinch is None or len(self._touches) < 2:
            return False
        distance = max(self._finger_distance(), 1.0)
        mid = self._finger_mid()
        self._live_scale = min(max(distance / max(self._pinch["distance"], 1.0), 0.2), 6.0)
        self._live_dx = mid[0] - self._pinch["mid"][0]
        self._live_dy = mid[1] - self._pinch["mid"][1]
        self._redraw()
        return True

    def on_touch_up(self, touch):
        if touch.uid not in self._touches:
            return super().on_touch_up(touch)
        del self._touches[touch.uid]
        if self._pinch is not None:
            self._commit_gesture()
        return True

    def _finger_distance(self) -> float:
        pts = [held.pos for held in list(self._touches.values())[:2]]
        if len(pts) < 2:
            return 1.0
        distance = math.hypot(pts[0][0] - pts[1][0], pts[0][1] - pts[1][1])
        return max(distance, 1.0)

    def _finger_mid(self):
        pts = [held.pos for held in list(self._touches.values())[:2]]
        if len(pts) < 2:
            return self.center
        return ((pts[0][0] + pts[1][0]) / 2.0, (pts[0][1] + pts[1][1]) / 2.0)

    def _reset_live(self) -> None:
        self._live_scale = 1.0
        self._live_dx = 0.0
        self._live_dy = 0.0

    def _release_touches(self) -> None:
        for held in list(self._touches.values()):
            if held.grab_current is self:
                held.ungrab(self)
        self._touches.clear()
        self._pinch = None

    def _commit_gesture(self) -> None:
        """Fold the live pan/zoom into a viewport and re-render the tiles."""
        moved = self._live_scale != 1.0 or self._live_dx or self._live_dy
        self._release_touches()
        render = self._render
        if render is None or not moved:
            self._reset_live()
            return
        # Local import: importing tile_map is cheap (Pillow loads lazily).
        from ui.services.tile_map import fold_gesture

        zoom, lat, lon = fold_gesture(
            render, self._live_dx, self._live_dy, self._live_scale,
        )
        self._view = (zoom, lat, lon)
        self._reset_live()
        self._redraw()
        self._request_basemap()

    def _zoom_by(self, delta: int) -> None:
        """One zoom step, centred on the current view."""
        render = self._render
        if render is None:
            return
        target = max(
            config.Config.TILE_MIN_ZOOM,
            min(render.zoom + delta, config.Config.TILE_MAX_ZOOM),
        )
        if target == render.zoom:
            return
        lat, lon = render.unproject(0.5, 0.5)
        # Instant feedback on the texture already on screen; the crisp tiles
        # land as soon as the worker returns.
        self._live_scale = 2.0 ** (target - render.zoom)
        self._live_dx = 0.0
        self._live_dy = 0.0
        self._view = (target, lat, lon)
        self._redraw()
        self._request_basemap()

    def _set_hint(self, message: str) -> None:
        self._hint.text = message
        self._hint.opacity = 1 if message else 0
        self._layout_hint()

    def _layout_children(self) -> None:
        """Place the zoom buttons and the caption (this widget has no layout)."""
        size = dp(30)
        margin = dp(6)
        maps_ready = self._basemap is not None
        for button in (self._zoom_in, self._zoom_out):
            button.size = (size, size)
            button.disabled = not maps_ready
        self._zoom_in.pos = (self.right - size - margin, self.center_y + margin / 2.0)
        self._zoom_out.pos = (self.right - size - margin, self.center_y - size - margin / 2.0)
        self._layout_hint()

    def _layout_hint(self) -> None:
        if not self._hint.text:
            return
        self._hint.text_size = (max(self.width - dp(16), dp(40)), None)
        self._hint.texture_update()
        self._hint.size = self._hint.texture_size
        self._hint.center = self.center

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def _map_points(self, x: float, y: float, width: float, height: float):
        """Stop positions read off the basemap projection (Kivy is y-up)."""
        points = []
        for lat, lon in self.stops:
            fx, fy = self._project(lat, lon)
            points.append((x + fx * width, y + (1.0 - fy) * height))
        return points

    def _schematic_points(self, x: float, y: float, width: float, height: float):
        """Offline fallback: stretch the tour across the whole canvas."""
        lats = [point[0] for point in self.stops]
        lons = [point[1] for point in self.stops]
        lat_span = max(max(lats) - min(lats), 0.002)
        lon_span = max(max(lons) - min(lons), 0.002)
        margin = dp(24)
        return [
            (
                x + margin + ((lon - min(lons)) / lon_span) * max(width - margin * 2, 1),
                y + margin + ((max(lats) - lat) / lat_span) * max(height - margin * 2, 1),
            )
            for lat, lon in self.stops
        ]

    def _redraw(self, *_args) -> None:
        self._dynamic.clear()
        x, y = self.pos
        width, height = self.size
        scale = self._live_scale
        dx, dy = self._live_dx, self._live_dy
        center_x, center_y = self.center
        with self._dynamic:
            Color(*PANEL)
            Rectangle(pos=self.pos, size=self.size)
            on_map = self._basemap is not None and self._project is not None
            # Everything is clipped to the map box: while panning, the texture
            # and the route deliberately extend past it and would otherwise
            # paint over the form below (same stencil recipe Kivy uses for
            # Image and ScrollView).
            StencilPush()
            Rectangle(pos=self.pos, size=self.size)
            StencilUse()
            if on_map:
                Color(1, 1, 1, 1)
                Rectangle(
                    texture=self._basemap,
                    pos=(center_x - width * scale / 2.0 + dx,
                         center_y - height * scale / 2.0 + dy),
                    size=(width * scale, height * scale),
                )
            else:
                # Grid placeholder until the tiles land (or when they cannot).
                Color(0.19, 0.30, 0.43, 1)
                for fraction in (0.25, 0.5, 0.75):
                    Line(points=[x + width * fraction, y, x + width * fraction, y + height], width=1)
                    Line(points=[x, y + height * fraction, x + width, y + height * fraction], width=1)
            if self.stops:
                points = (
                    self._map_points(x, y, width, height)
                    if on_map
                    else self._schematic_points(x, y, width, height)
                )
                if len(points) == 1 and not on_map:
                    points = [(x + width / 2, y + height / 2)]
                # Same transform as the texture, so the route stays glued to
                # the streets while a pinch is in progress.
                points = [
                    (center_x + (px - center_x) * scale + dx,
                     center_y + (py - center_y) * scale + dy)
                    for px, py in points
                ]
                if len(points) > 1:
                    Color(*ORANGE)
                    Line(points=[coordinate for point in points for coordinate in point], width=dp(2))
                for index, (px, py) in enumerate(points):
                    Color(*(MINT if index == 0 else ORANGE))
                    radius = dp(8 if index == 0 else 6)
                    Ellipse(pos=(px - radius, py - radius), size=(radius * 2, radius * 2))
            StencilUnUse()
            Rectangle(pos=self.pos, size=self.size)
            StencilPop()
        self._layout_children()


class SafeTransAsScreen(BoxLayout):
    """Circuit-style, GPU-conservative delivery route planner."""

    def __init__(self, db: DBManager, controller: OptimizeController, **kwargs):
        super().__init__(orientation="vertical", padding=(dp(14), dp(16)), spacing=dp(10), **kwargs)
        self._db = db
        self._controller = controller
        self._controller.bind(progress_cb=self._on_progress, finished_cb=self._on_finished, error_cb=self._on_error)
        with self.canvas.before:
            Color(*NAVY)
            self._background = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._sync_background, size=self._sync_background)

        self._delete_armed = False
        self._blocks = {}
        self._state = (False, False)  # (des arrêts existent, tournée géocodée)
        self._keyboard_open = False
        Window.bind(on_keyboard=self._on_back_key, on_touch_down=self._on_global_touch)
        header = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
        # MENU, title, summary and OPTIONS share 279 dp of usable width on
        # this phone, so the buttons take only the width their caption needs
        # and the title drops to a single line.
        menu_left = self._button("MENU", (0.12, 0.22, 0.35, 1), width=dp(60))
        menu_left.font_size = "12sp"
        menu_left.bind(on_release=lambda _button: self._toggle_menu("left"))
        header.add_widget(menu_left)
        header.add_widget(self._label("TransAs", "16sp", WHITE, bold=True, shorten=True))
        self._route_summary = self._label("Ma tournée", "14sp", MUTED, halign="right")
        header.add_widget(self._route_summary)
        menu_right = self._button("OPTIONS", (0.12, 0.22, 0.35, 1), width=dp(76))
        menu_right.font_size = "11sp"
        menu_right.bind(on_release=lambda _button: self._toggle_menu("right"))
        header.add_widget(menu_right)
        self.add_widget(header)
        # Everything below the header lives in a single scroll region.  The
        # fixed chrome alone (≈668 dp) used to be taller than the grid this
        # phone gives Kivy (≈638 dp), so the stop list was laid out past the
        # bottom edge: stops could be imported while the screen stayed empty.
        # spacing=0: each block brings its own top margin inside its foldable
        # holder, so a folded block costs no gap (see ``_Collapsible``).
        content = BoxLayout(orientation="vertical", spacing=0, size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))
        # Only "+ STOP" and "OPTIMISER L'ORDRE" stay on the screen; everything
        # else lives in the MENU / OPTIONS popups (El-hadj, 27/10/2026). That
        # hands ~92 dp back to the map and to the field being typed in, which
        # the Android keyboard covers on a 638 dp-tall canvas.
        # The third element is an availability test: an action that cannot do
        # anything right now is drawn greyed out rather than hidden, so the
        # menu does not shuffle under the driver's finger.
        self._left_actions = [
            ("Créer un nouveau trajet", self._new_trip, None),
            ("Se connecter", self._login, None),
        ]
        self._right_actions = [
            ("Naviguer vers le prochain arrêt", self._navigate_next, self._has_route),
            ("Réoptimiser depuis ma position", self._reoptimize_from_here, self._has_parcels),
            ("Importer un fichier CSV", self._open_batch_import, None),
            ("Ajouter par voix", self._add_by_voice, None),
            ("Partager le trajet", self._share_route, self._has_parcels),
            ("Imprimer le trajet", self._print_route, self._has_parcels),
            ("Supprimer les arrêts", self._delete_stops, self._has_parcels),
        ]
        # The actions are displayed in a modal popup (see ``_toggle_menu``).
        # Keeping the menus out of the main vertical layout is important on
        # tall Android screens: expanding an inline menu while its own button
        # is being released can move another action underneath the finger and
        # trigger it by mistake. The popup is rebuilt on each click —
        # no inline placeholder widgets are added to the parent layout.
        # Every block below hangs under a foldable holder (see ``_Collapsible``)
        # and ``self._blocks`` maps its name to that holder, so
        # ``_apply_layout`` can fold away what the current state does not need.
        self._map = RouteMap(size_hint_y=None, height=dp(170))
        content.add_widget(self._block("map", self._map))
        self._status = self._label("Ajoute des arrêts pour commencer la tournée.", "14sp", MUTED, size_hint_y=None, height=dp(32))
        content.add_widget(self._block("status", self._status))
        self._tour_kpi = self._label("0 livré · 0 en attente", "13sp", MUTED, size_hint_y=None, height=dp(22))
        content.add_widget(self._block("kpi", self._tour_kpi))

        next_stop_box = BoxLayout(size_hint_y=None, height=dp(38), padding=(dp(10), dp(2)))
        # The label owns an explicit height, so the box follows it instead of
        # cropping a long "next stop" address.
        next_stop_box.bind(minimum_height=next_stop_box.setter("height"))
        with next_stop_box.canvas.before:
            Color(0.12, 0.22, 0.35, 1)
            next_box_bg = Rectangle(pos=next_stop_box.pos, size=next_stop_box.size)
        next_stop_box.bind(
            pos=lambda widget, _value, rect=next_box_bg: setattr(rect, "pos", widget.pos),
            size=lambda widget, _value, rect=next_box_bg: setattr(rect, "size", widget.size),
        )
        self._next_stop_label = self._label(
            "Prochain arrêt : optimise d'abord.", "13sp", WHITE,
            size_hint_y=None, height=dp(34),
        )
        next_stop_box.add_widget(self._next_stop_label)
        content.add_widget(self._block("next", next_stop_box))

        points = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        self._start_address = TextInput(hint_text="Départ", multiline=False, background_color=(0.12, 0.22, 0.35, 1), foreground_color=WHITE)
        self._end_address = TextInput(hint_text="Arrivée", multiline=False, background_color=(0.12, 0.22, 0.35, 1), foreground_color=WHITE)
        points.add_widget(self._start_address)
        points.add_widget(self._end_address)
        content.add_widget(self._block("points", points))

        entry = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        self._address = TextInput(hint_text="Ajouter une adresse", multiline=False, background_color=(0.12, 0.22, 0.35, 1), foreground_color=WHITE)
        entry.add_widget(self._address)
        add = self._button("+ STOP", ORANGE, width=dp(92))
        add.bind(on_release=lambda _button: self._add_parcel())
        entry.add_widget(add)
        content.add_widget(self._block("entry", entry))

        actions = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        self._optimize_button = self._button("OPTIMISER L'ORDRE", MINT)
        self._optimize_button.bind(on_release=lambda _button: self._optimize())
        actions.add_widget(self._optimize_button)
        content.add_widget(self._block("optimize", actions))

        self._rows = BoxLayout(orientation="vertical", spacing=dp(7), size_hint_y=None)
        self._rows.bind(minimum_height=self._rows.setter("height"))
        content.add_widget(self._block("rows", self._rows))

        # The IME covers about 40 % of this screen, so the layout folds the
        # heavy blocks as soon as a field takes focus (``below_target`` pans
        # the window at the same time — see ``main._enable_soft_keyboard_panning``).
        for field in (self._address, self._start_address, self._end_address):
            field.bind(focus=self._on_field_focus)

        page = ScrollView(do_scroll_x=False, bar_color=ORANGE, bar_width=dp(3))
        page.add_widget(content)
        self.add_widget(page)
        self.refresh()

    @staticmethod
    def _label(text: str, font_size: str, color, **kwargs) -> Label:
        """Build a label that never hides the start of its own message.

        ``text_size`` is bound to the widget size so long addresses wrap, but
        Kivy then anchors the wrapped block to the *bottom* of the box: on a
        narrow phone every message wrapped and only its last line stayed
        visible ("Ajoute des arrêts pour commencer la tournée." rendered as
        "tournée.").  Anchoring to the top keeps the beginning readable, and
        an explicit ``height`` now acts as a floor the label grows past
        instead of a hard clip.
        """
        label = Label(text=text, font_size=font_size, color=color, valign="top", **kwargs)
        if kwargs.get("size_hint_y") is None and "height" in kwargs:
            # Message labels own their height, so leave the height side of
            # ``text_size`` unconstrained: a set height clamps texture_size
            # (Kivy crops the text to the box) which would freeze the label
            # at one line.  Free of it, the real wrapped height comes back
            # and the given height only acts as a floor.
            floor = kwargs["height"]
            label.bind(
                size=lambda instance, _size: setattr(
                    instance, "text_size", (instance.width, None)
                )
            )
            label.bind(
                texture_size=lambda instance, size, low=floor: setattr(
                    instance, "height", max(low, size[1])
                )
            )
        else:
            # Width-driven labels (list rows, popup messages) keep a bounded
            # box: Kivy crops what overflows it instead of painting over the
            # neighbouring widget.
            label.bind(size=lambda instance, _size: setattr(instance, "text_size", instance.size))
        return label

    @staticmethod
    def _button(text: str, color, width=None, text_color=None) -> Button:
        """Create a high-contrast touch target on every screen density."""
        if text_color is None:
            # Navy and slate surfaces need white text.  Bright action colours
            # (mint/orange) keep the dark text used by the main controls.
            text_color = WHITE if sum(color[:3]) < 1.35 else NAVY
        kwargs = {
            "text": text,
            "background_normal": "",
            "background_color": color,
            "color": text_color,
            "bold": True,
            "font_size": "15sp",
        }
        if width is not None:
            kwargs.update(size_hint_x=None, width=width)
        return Button(**kwargs)

    def _toggle_menu(self, which: str) -> None:
        actions = self._left_actions if which == "left" else self._right_actions
        title = "Menu" if which == "left" else "Options"
        root = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        scroll = ScrollView(do_scroll_x=False, bar_color=ORANGE, bar_width=dp(3))
        action_list = BoxLayout(orientation="vertical", spacing=dp(8), size_hint_y=None)
        action_list.bind(minimum_height=action_list.setter("height"))
        scroll.add_widget(action_list)
        root.add_widget(scroll)
        popup = Popup(
            title=title,
            content=root,
            size_hint=(0.92, None),
            # Cap the height so OPTIONS remains usable in landscape and on
            # compact devices; its list becomes scrollable when necessary.
            height=min(dp(92 + 60 * len(actions)), dp(560)),
            auto_dismiss=True,
        )
        for action in actions:
            text, callback = action[0], action[1]
            available = action[2] if len(action) > 2 else None
            button = self._button(text, (0.12, 0.22, 0.35, 1))
            button.size_hint_y = None
            button.height = dp(52)
            if available is not None:
                button.disabled = not available()

            def run_action(_button, action=callback, menu=popup):
                menu.dismiss()
                # The next popup/Android Intent must be created after the
                # menu has completed its dismiss cycle.  Otherwise Android
                # may show an empty-looking window on some Samsung builds.
                Clock.schedule_once(lambda _dt: action(), 0)

            button.bind(on_release=run_action)
            action_list.add_widget(button)
        popup.open()

    # ------------------------------------------------------------------
    # Dynamic layout — the screen shows only what the current state needs
    # ------------------------------------------------------------------

    def _block(self, name: str, widget, gap=dp(8)) -> "_Collapsible":
        """Wrap a layout block in its foldable holder and remember it by name."""
        holder = _Collapsible(gap=gap)
        holder.add_widget(widget)
        self._blocks[name] = holder
        return holder

    def _has_parcels(self) -> bool:
        """True when at least one stop is waiting to be delivered."""
        return bool(self._db.list_pending())

    def _has_route(self) -> bool:
        """True when a stop is geocoded, i.e. navigation can be started."""
        return any(parcel.coords for parcel in self._db.list_pending())

    def _on_back_key(self, _window, key, *_args) -> bool:
        """Close the keyboard instead of leaving the app on BACK.

        Android delivers the back button to Kivy as ESCAPE (key 27). With a
        field focused, an unhandled BACK used to send the activity home while
        the layout stayed folded; consuming it here unfocuses the field, which
        closes the IME and restores the blocks (see ``_on_field_focus``).
       Returning ``True`` marks the event as handled so the task stays alive.
        """
        if key == 27 and self._keyboard_open:
            _logger.info("BACK key consumed: closing keyboard and restoring")
            for field in (self._address, self._start_address, self._end_address):
                field.focus = False
            # Belt and braces: losing focus normally reruns _apply_layout via
            # _on_field_focus, but force the restore in case Kivy folds the
            # property events on this device.
            self._keyboard_open = False
            self._apply_layout()
            return True
        return False

    def _on_global_touch(self, _window, touch) -> bool:
        """Treat a tap outside the text fields as "done typing".

        Some Android layers swallow the back button before it reaches Kivy
        (the system dismisses the IME itself), which would leave the layout
        folded for ever; tapping anything that is not an input field then
        restores the blocks. Touches on the fields themselves are left alone
        so the keyboard still opens/stays for them.
        """
        if not self._keyboard_open:
            return False
        x, y = touch.pos
        for field in (self._address, self._start_address, self._end_address):
            fx, fy = field.to_window(*field.pos)
            if fx <= x <= fx + field.width and fy <= y <= fy + field.height:
                return False
        _logger.info("tap outside inputs: restoring layout")
        for field in (self._address, self._start_address, self._end_address):
            field.focus = False
        self._keyboard_open = False
        self._apply_layout()
        return False

    def _on_field_focus(self, _field, focused: bool) -> None:
        """Fold the heavy blocks while the keyboard is up.

        SDL reports ``keyboard_height == 0`` on Android, so the IME height
        cannot be measured; focus on a text field is the reliable signal that
        the keyboard is on screen.
        """
        self._keyboard_open = bool(focused)
        self._apply_layout()

    def _apply_layout(self) -> None:
        """Fold or unfold each block for the current state.

        Everything that is only useful once a tour exists (KPIs, next stop,
        stop list, optimise button) appears with the first stop; the map and
        the list fold away while the keyboard is open so the field being
        typed in stays visible above the IME.
        """
        has_stops, has_route = self._state
        typing = self._keyboard_open
        visibility = {
            "map": not typing,
            "status": True,
            "kpi": has_stops and not typing,
            "next": has_route and not typing,
            "points": has_stops,
            "entry": True,
            "optimize": has_stops,
            "rows": has_stops and not typing,
        }
        for name, holder in self._blocks.items():
            holder.collapsed = not visibility.get(name, False)

    def _new_trip(self) -> None:
        self._start_address.text = ""
        self._end_address.text = ""
        self._delete_armed = False
        self._status.text = "Nouveau trajet prêt : ajoute tes arrêts."

    def _login(self) -> None:
        root = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        name = TextInput(hint_text="Nom du conducteur", multiline=False)
        email = TextInput(hint_text="E-mail (optionnel)", multiline=False)
        root.add_widget(name)
        root.add_widget(email)
        popup = Popup(title="Profil conducteur", content=root, size_hint=(0.9, 0.42), auto_dismiss=False)
        actions = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        cancel = self._button("ANNULER", (0.20, 0.34, 0.53, 1))
        save = self._button("ENREGISTRER", MINT)
        cancel.bind(on_release=lambda _button: popup.dismiss())
        def persist(_button):
            if not name.text.strip():
                name.hint_text = "Le nom est requis"
                return
            store = JsonStore(str(self._db.db_path) + ".profile.json")
            store.put("driver", name=name.text.strip(), email=email.text.strip())
            popup.dismiss()
            self._status.text = f"Profil enregistré : {name.text.strip()}."
        save.bind(on_release=persist)
        actions.add_widget(cancel)
        actions.add_widget(save)
        root.add_widget(actions)
        popup.open()

    def _add_by_voice(self) -> None:
        started = request_address(
            lambda address: self._on_voice_address(address),
            lambda message: setattr(self._status, "text", message),
        )
        if started:
            self._status.text = "Écoute en cours : dicte l'adresse complète."

    def _on_voice_address(self, address: str) -> None:
        self._address.text = address
        self._status.text = "Adresse dictée : vérifie-la puis appuie sur + STOP."

    def _route_text(self) -> str:
        parcels = self._ordered_pending()
        lines = ["TransAs — tournée du jour"]
        if self._start_address.text.strip():
            lines.append(f"Départ : {self._start_address.text.strip()}")
        lines.extend(f"{index}. {parcel.address}" for index, parcel in enumerate(parcels, start=1))
        if self._end_address.text.strip():
            lines.append(f"Arrivée : {self._end_address.text.strip()}")
        return "\n".join(lines)

    def _share_text(self, title: str) -> bool:
        try:
            from kivy.utils import platform
            if platform != "android":
                return False
            from jnius import autoclass  # type: ignore[import-not-found]
            Intent = autoclass("android.content.Intent")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            intent = Intent(Intent.ACTION_SEND)
            intent.setType("text/plain")
            intent.putExtra(Intent.EXTRA_TEXT, self._route_text())
            PythonActivity.mActivity.startActivity(Intent.createChooser(intent, title))
            return True
        except Exception:
            return False

    def _share_route(self) -> None:
        self._status.text = "Choisis l'application de partage." if self._share_text("Partager la tournée") else "Partage indisponible sur cet appareil."

    def _print_route(self) -> None:
        self._status.text = "Choisis le service d'impression ou PDF." if self._share_text("Imprimer la tournée") else "Impression indisponible sur cet appareil."

    def _delete_stops(self) -> None:
        pending = self._db.list_pending()
        if not pending:
            self._status.text = "Il n'y a aucun arrêt à supprimer."
            return
        root = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(10))
        message = self._label(
            f"Supprimer définitivement les {len(pending)} arrêt(s) en attente ?",
            "17sp", NAVY,
        )
        root.add_widget(message)
        actions = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8))
        popup = Popup(
            title="Confirmer la suppression",
            content=root,
            size_hint=(0.9, None),
            height=dp(210),
            auto_dismiss=False,
        )
        cancel = self._button("ANNULER", (0.20, 0.34, 0.53, 1))
        confirm = self._button("SUPPRIMER", ORANGE)
        cancel.bind(on_release=lambda _button: popup.dismiss())

        def confirm_delete(_button):
            for parcel in self._db.list_pending():
                self._db.delete_parcel(parcel.id)
            popup.dismiss()
            self._delete_armed = False
            self._status.text = "Tous les arrêts en attente ont été supprimés."
            self.refresh()

        confirm.bind(on_release=confirm_delete)
        actions.add_widget(cancel)
        actions.add_widget(confirm)
        root.add_widget(actions)
        popup.open()

    def _sync_background(self, *_args) -> None:
        self._background.pos, self._background.size = self.pos, self.size

    def _add_parcel(self) -> None:
        address = self._address.text.strip()
        if not address:
            self._status.text = "Saisis une adresse avant d'ajouter un arrêt."
            return
        try:
            parcel_id = self._db.add_parcel(address)
        except (TypeError, ValueError) as exc:
            self._status.text = f"Adresse refusée : {exc}"
            return
        self._address.text = ""
        self._status.text = f"Arrêt #{parcel_id} ajouté — appuie sur OPTIMISER."
        self.refresh()

    def _open_batch_import(self) -> None:
        root = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        root.add_widget(self._label(
            "Colle une adresse par ligne ou un CSV avec colonne Adresse.",
            "15sp", NAVY, size_hint_y=None, height=dp(46),
        ))
        source = TextInput(multiline=True, hint_text="Adresse\n12 rue Exemple, 75001 Paris")
        root.add_widget(source)
        actions = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        popup = Popup(title="Importer des arrêts", content=root, size_hint=(0.94, 0.72), auto_dismiss=False)
        cancel = self._button("ANNULER", (0.20, 0.34, 0.53, 1))
        cancel.bind(on_release=lambda _button: popup.dismiss())
        confirm = self._button("IMPORTER", MINT)
        def import_now(_button):
            try:
                addresses = parse_addresses(source.text)
                if not addresses:
                    raise ValueError("Aucune adresse détectée")
                for address in addresses:
                    self._db.add_parcel(address)
            except (TypeError, ValueError) as exc:
                source.hint_text = f"Import impossible : {exc}"
                return
            popup.dismiss()
            self._status.text = f"{len(addresses)} arrêts importés. Appuie sur OPTIMISER."
            self.refresh()
        confirm.bind(on_release=import_now)
        actions.add_widget(cancel)
        actions.add_widget(confirm)
        root.add_widget(actions)
        popup.open()

    def _optimize(self) -> None:
        parcels = [ParcelInput(id=p.id, address=p.address, lat=p.lat, lon=p.lon) for p in self._db.list_pending()]
        if not parcels:
            self._status.text = "Ajoute au moins un arrêt."
            return
        self._optimize_button.disabled = True
        self._status.text = "Calcul de la meilleure tournée…"
        try:
            start_text = self._start_address.text.strip()
            end_text = self._end_address.text.strip()
            if bool(start_text) != bool(end_text):
                self._optimize_button.disabled = False
                self._status.text = "Renseigne à la fois le départ et l'arrivée."
                return
            start = ParcelInput(id=-1, address=start_text) if start_text else None
            end = ParcelInput(id=-2, address=end_text) if end_text else None
            self._controller.start_geocode_then_optimize(parcels, start_point=start, end_point=end)
        except RuntimeError:
            self._status.text = "Optimisation déjà en cours."
        except Exception as exc:
            self._optimize_button.disabled = False
            self._status.text = f"Optimisation impossible : {exc}"

    # ------------------------------------------------------------------
    # RÉOPTIMISER D'ICI — start the remaining tour from the driver's GPS fix
    # ------------------------------------------------------------------

    def _pending_inputs(self) -> list[ParcelInput]:
        return [
            ParcelInput(id=p.id, address=p.address, lat=p.lat, lon=p.lon)
            for p in self._db.list_pending()
        ]

    def _reoptimize_from_here(self) -> None:
        parcels = self._pending_inputs()
        if not parcels:
            self._status.text = "Ajoute au moins un arrêt."
            return
        if self._controller.is_running:
            self._status.text = "Optimisation déjà en cours."
            return
        if has_permission():
            self._start_position_search()
            return
        if request_permission(self._on_location_permission):
            self._status.text = "Autorise la localisation pour partir d'ici."
        else:
            self._status.text = "Localisation indisponible — saisis le départ à la main."

    def _on_location_permission(self, granted: bool) -> None:
        if granted:
            self._start_position_search()
            return
        self._status.text = "Localisation refusée — saisis le départ à la main."

    def _start_position_search(self) -> None:
        self._status.text = "Recherche de ta position…"
        request_position(self._on_position)

    def _on_position(self, position, error) -> None:
        if position is None:
            self._status.text = error or "Position introuvable."
            return
        lat, lon = position
        parcels = self._pending_inputs()
        if not parcels:
            self._status.text = "Ajoute au moins un arrêt."
            return
        start = ParcelInput(id=-1, address="Ma position", lat=lat, lon=lon)
        self._status.text = "Position trouvée — réoptimisation depuis ici…"
        self._optimize_button.disabled = True
        try:
            self._controller.start_geocode_then_optimize(parcels, start_point=start)
        except RuntimeError:
            self._status.text = "Optimisation déjà en cours."
        except Exception as exc:
            self._status.text = f"Optimisation impossible : {exc}"

    def _on_progress(self, done: int, total: int, label: str) -> None:
        self._status.text = f"{label}  {done}/{total}"

    def _on_finished(self, result: OptimizeResult) -> None:
        self._optimize_button.disabled = False
        self._status.text = f"Tournée optimisée · {result.total_distance_m / 1000:.1f} km · {result.matrix_source}"
        if result.start_point and result.end_point:
            self._start_address.text = result.start_point.address
            self._end_address.text = result.end_point.address
        self.refresh()

    def _on_error(self, exc: BaseException) -> None:
        self._optimize_button.disabled = False
        self._status.text = f"Optimisation impossible : {exc}"

    def _ordered_pending(self):
        pending = self._db.list_pending()
        tour = self._db.load_today_tour()
        if not tour:
            return pending
        by_id = {parcel.id: parcel for parcel in pending}
        ordered = [by_id.pop(parcel_id) for parcel_id in tour.ordered_indices if parcel_id in by_id]
        return ordered + list(by_id.values())

    def refresh(self) -> None:
        parcels = self._ordered_pending()
        all_parcels = self._db.list_all()
        delivered_count = max(len(all_parcels) - len(parcels), 0)
        # Feeds the dynamic layout: what exists, and whether navigation is
        # already possible.
        self._state = (bool(parcels), any(parcel.coords for parcel in parcels))
        self._tour_kpi.text = f"{delivered_count} livré{'s' if delivered_count != 1 else ''} · {len(parcels)} en attente"
        # Always show the default operational area rather than an empty grid.
        # The location moves to the route's geographical bounds once stops
        # are available.
        coords = [(parcel.lat, parcel.lon) for parcel in parcels if parcel.coords] or [DEFAULT_CITY]
        self._map.set_stops(coords)
        self._route_summary.text = f"{len(parcels)} arrêt{'s' if len(parcels) != 1 else ''}"
        next_stop = next((parcel for parcel in parcels if parcel.coords), None)
        self._next_stop_label.text = (
            f"Prochain arrêt : {next_stop.address}"
            if next_stop is not None
            else "Prochain arrêt : optimise pour activer la navigation."
        )
        self._rows.clear_widgets()
        if not parcels:
            # Nothing to list: the empty-state placeholder is gone, the layout
            # folds the list away and the status line already says what to do.
            self._apply_layout()
            return
        for index, parcel in enumerate(parcels, start=1):
            row = BoxLayout(size_hint_y=None, height=dp(68), padding=(dp(10), dp(5)), spacing=dp(8))
            with row.canvas.before:
                Color(*PANEL)
                rectangle = Rectangle(pos=row.pos, size=row.size)
            row.bind(pos=lambda widget, _value, rect=rectangle: setattr(rect, "pos", widget.pos), size=lambda widget, _value, rect=rectangle: setattr(rect, "size", widget.size))
            row.add_widget(self._label(str(index), "20sp", MINT if index == 1 else ORANGE, size_hint_x=None, width=dp(32)))
            gps = "GPS prêt" if parcel.coords else "GPS à trouver"
            row.add_widget(self._label(f"{parcel.address}\n{gps}", "14sp", WHITE))
            delivered = self._button("LIVRÉ", (0.24, 0.36, 0.49, 1), width=dp(76))
            delivered.bind(on_release=lambda _button, parcel_id=parcel.id: self._deliver(parcel_id))
            row.add_widget(delivered)
            self._rows.add_widget(row)
        self._apply_layout()

    def _deliver(self, parcel_id: int) -> None:
        self._db.mark_delivered(parcel_id)
        self._status.text = "Arrêt marqué livré. Prochain arrêt affiché."
        Clock.schedule_once(lambda _dt: self.refresh(), 0)

    def _navigate_next(self) -> None:
        next_stop = next((parcel for parcel in self._ordered_pending() if parcel.coords), None)
        if next_stop is None:
            self._status.text = "Optimise une tournée avec au moins un arrêt géocodé."
            return
        if open_navigation(next_stop.lat, next_stop.lon, next_stop.address):
            self._status.text = "Navigation ouverte vers le prochain arrêt."
        else:
            self._status.text = "Aucune application de navigation disponible."
