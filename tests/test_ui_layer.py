"""Tests for the Étape 3 UI layer (Kivy/KivyMD).

We test without spinning up Kivy:
  * ``ui.services.folium_renderer`` (pure Pillow).
  * ``ui.services.uri_utils`` (pure urllib).
  * ``ui.controllers.optimize_controller.OptimizeController`` with stubbed
    ``core/`` and a SQL-free in-memory DB stub.

Kivy widget-tree tests are deferred (would need a window + GL context).
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import List
from unittest import mock

import pytest

# Project root on ``sys.path`` is set up by ``conftest.py`` at the
# project root (pytest's rootdir mechanism picks it up automatically).
# This module no longer duplicates the sys.path step (removed 2026-07-15).


# ---------------------------------------------------------------------------
# 1. folium_renderer — pure Pillow
# ---------------------------------------------------------------------------

def test_folium_renderer_creates_png(tmp_path):
    from ui.services.folium_renderer import render_route_png
    coords = [
        (48.8530, 2.3499), (48.8606, 2.3376),
        (48.8716, 2.3430), (48.8533, 2.3692),
    ]
    ordered = [0, 1, 2, 3]
    out = render_route_png(coords, ordered, output_path=tmp_path / "map.png")
    assert out.exists()
    from PIL import Image
    img = Image.open(out)
    assert img.format == "PNG"
    assert img.size[0] >= 100 and img.size[1] >= 100


def test_folium_renderer_handles_empty_coords(tmp_path):
    from ui.services.folium_renderer import render_route_png
    out = render_route_png([], [], output_path=tmp_path / "empty.png")
    assert out.exists()
    from PIL import Image
    assert Image.open(out).format == "PNG"


def test_folium_renderer_returns_bytes():
    from ui.services.folium_renderer import render_route_bytes
    coords = [(48.853, 2.350), (48.860, 2.338)]
    raw = render_route_bytes(coords, [0, 1])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"


def test_folium_renderer_centering_is_symmetric():
    """Verify the project function now offsets on BOTH axes."""
    from ui.services.folium_renderer import _project
    # Tall & narrow bounding box — only X should be centred (Y span
    # meets the canvas). Then a wide box — X span meets, Y offset used.
    pts_wide = _project([(48.0, 0.0), (49.0, 0.0001)], width=720, height=1280)
    pts_narrow = _project([(48.0, 0.0), (48.0001, 0.01)], width=720, height=1280)
    # All output points must fall within ``(margin, width - margin)``.
    margin = 48
    for x, y in pts_wide + pts_narrow:
        assert margin < x < (720 - margin)
        assert margin < y < (1280 - margin), (
            f"point ({x},{y}) outside the margin-ish canvas strip"
        )


# ---------------------------------------------------------------------------
# 2. uri_utils — Android geo: scheme helpers (NO Kivy imports)
# ---------------------------------------------------------------------------

def test_sanitize_label_strips_uri_chars():
    from ui.services.uri_utils import sanitize_label
    label = sanitize_label("12, rue de l'Été\n75001 Paris #foo!")
    for forbidden in (",", "'", "\n", "#", "!"):
        assert forbidden not in label
    assert len(label) <= 60


def test_build_geo_uri_encodes_label():
    """Spaces in the label become %20 (NOT raw spaces) — otherwise Android
    Intent parser splits on the first space and drops the rest."""
    from ui.services.uri_utils import build_geo_uri
    uri = build_geo_uri(48.8530, 2.3499, "12 rue de l'Été 75001 Paris")
    assert "%20" in uri, f"label not URL-encoded: {uri}"
    assert " " not in uri.split("?q=", 1)[-1], (
        "the label segment still contains raw spaces"
    )


def test_build_geo_uri_no_label():
    from ui.services.uri_utils import build_geo_uri
    assert build_geo_uri(48.85, 2.35) == "geo:48.85,2.35"


def test_build_google_maps_web_url_format():
    from ui.services.uri_utils import build_google_maps_web_url
    url = build_google_maps_web_url(48.85, 2.35)
    assert url.startswith("https://www.google.com/maps/search/")
    assert "48.85" in url and "2.35" in url


def test_navigation_desktop_uses_google_maps(monkeypatch):
    from ui.services import navigation
    opened = {}
    monkeypatch.setattr(navigation.sys, "platform", "linux")
    monkeypatch.setattr(navigation.webbrowser, "open", lambda url: opened.setdefault("url", url) or True)
    assert navigation.open_navigation(48.85, 2.35, "Paris") is True
    assert "48.85,2.35" in opened["url"]


def _stub_kivy_utils(monkeypatch, platform_value):
    """Register a fake ``kivy.utils`` module so Kivy need not be installed.

    Kivy ships no CPython 3.14 wheel and the dev venv has no 3.12 any more,
    so ``import kivy`` is impossible here; the code under test only reads the
    ``kivy.utils.platform`` marker.  ``monkeypatch.setitem`` removes the stub
    afterwards, restoring the real import behaviour for the other tests.
    """
    import sys
    import types

    kivy = types.ModuleType("kivy")
    utils = types.ModuleType("kivy.utils")
    utils.platform = platform_value
    kivy.utils = utils
    monkeypatch.setitem(sys.modules, "kivy", kivy)
    monkeypatch.setitem(sys.modules, "kivy.utils", utils)


def test_navigation_android_detection_uses_kivy_platform(monkeypatch):
    from ui.services import navigation
    monkeypatch.setattr(navigation.sys, "platform", "linux")
    _stub_kivy_utils(monkeypatch, "android")
    assert navigation._is_android() is True


def test_navigation_detection_prefers_kivy_marker_then_sys_platform(monkeypatch):
    import sys

    from ui.services import navigation
    monkeypatch.setattr(navigation.sys, "platform", "android")
    # Kivy present and non-Android: the marker wins over sys.platform.
    _stub_kivy_utils(monkeypatch, "linux")
    assert navigation._is_android() is False
    # Kivy absent (import raises): fall back to sys.platform.
    monkeypatch.setitem(sys.modules, "kivy", None)
    monkeypatch.setitem(sys.modules, "kivy.utils", None)
    assert navigation._is_android() is True


def test_batch_import_parses_csv_deduplicates_and_uses_address_column():
    from ui.services.batch_import import parse_addresses
    raw = "Adresse;Nom\n1 rue de Paris, 75001 Paris;A\n1 RUE DE PARIS, 75001 Paris;B\n2 rue de la Gare, 75010 Paris;C"
    assert parse_addresses(raw) == [
        "1 rue de Paris, 75001 Paris",
        "2 rue de la Gare, 75010 Paris",
    ]


def test_coords_label_format():
    from ui.services.uri_utils import coords_label
    assert coords_label(48.85, 2.35) == "48.8500, 2.3500"


# ---------------------------------------------------------------------------
# 3. OptimizeController — threaded pipeline (no Kivy, all stubs)
# ---------------------------------------------------------------------------

class _StubDB:
    """In-memory DB double for ``DBManager``."""
    def __init__(self):
        self.parcels: dict = {}
        self.tours: list = []
        self._next_id = 1

    def add_parcel(self, address, lat=None, lon=None):
        pid = self._next_id
        self._next_id += 1
        self.parcels[pid] = {"id": pid, "address": address, "lat": lat, "lon": lon}
        return pid

    def update_parcel_coords(self, pid, lat, lon):
        if pid in self.parcels:
            self.parcels[pid]["lat"] = lat
            self.parcels[pid]["lon"] = lon

    def save_tour(self, date_str, ordered_indices):
        self.tours.append((date_str, list(ordered_indices)))
        return len(self.tours)


def _patch_controller_for_test(monkeypatch, controller_module):
    """Force both emit helpers to direct-call (no Clock dependency)."""
    monkeypatch.setattr(
        controller_module, "_emit_main_thread",
        lambda cb, *a: cb(*a) if cb else None,
    )
    monkeypatch.setattr(
        controller_module.OptimizeController, "_emit_progress",
        lambda self, done, total, label:
            self._on_progress(done, total, label) if self._on_progress else None,
    )


def test_optimize_controller_synchronous_finish(monkeypatch):
    from ui.controllers import optimize_controller as oc
    _patch_controller_for_test(monkeypatch, oc)

    class _GR:
        def __init__(self, lat, lon):
            self.lat, self.lon = lat, lon
    monkeypatch.setattr(
        "core.geocoder.geocode",
        lambda addr, use_cache=True:
            {"A": _GR(48.85, 2.35), "B": _GR(48.86, 2.34)}.get(addr),
    )
    monkeypatch.setattr(
        "core.router.get_distance_matrix",
        lambda coords, **kw: [[0.0, 100.0], [100.0, 0.0]],
    )

    captured = {}
    errs = {}
    controller = oc.OptimizeController(db=_StubDB())
    controller.bind(
        progress_cb=lambda d, t, lbl: captured.setdefault("progress", []).append((d, t, lbl)),
        finished_cb=lambda r: captured.setdefault("finished", r),
        error_cb=lambda e: errs.setdefault("err", e),
    )
    inputs = [
        oc.ParcelInput(id=1, address="A"),
        oc.ParcelInput(id=2, address="B"),
    ]
    controller.start_geocode_then_optimize(inputs)
    assert controller._worker is not None
    controller._worker.join(timeout=10)
    assert not controller.is_running

    assert "finished" in captured, f"errors were: {errs.get('err')}"
    result = captured["finished"]
    assert result.total_distance_m == 100.0
    assert len(result.ordered_parcels) == 2
    assert {p.id for p in result.ordered_parcels} == {1, 2}
    # NEW: progress label must be visible — at least one "Géocodage…" label
    # must have been emitted during the pipeline.
    progress_labels = {entry[2] for entry in captured.get("progress", [])}
    assert any(lbl.startswith("Géocodage") for lbl in progress_labels), (
        f"label threading broken — got {captured.get('progress')!r}"
    )


def test_optimize_controller_rejects_empty():
    from ui.controllers import optimize_controller as oc
    controller = oc.OptimizeController(db=_StubDB())
    with pytest.raises(ValueError):
        controller.start_geocode_then_optimize([])


def test_optimize_controller_rejects_double_start(monkeypatch):
    """While a run is in flight, starting another raises ``RuntimeError``.

    Implementation note: the mocked geocoder finishes in <1 ms in tests,
    so without a synchronisation barrier the worker could finish BEFORE
    we reach the second ``start()`` and we would not see the rejection.
    We patch ``core.geocoder.geocode`` to block on a ``threading.Event``
    so the worker stays alive in the runtime state we want to test.
    """
    from ui.controllers import optimize_controller as oc
    _patch_controller_for_test(monkeypatch, oc)

    stop_event = threading.Event()
    class _GR:
        def __init__(self, lat, lon):
            self.lat, self.lon = lat, lon
    def _blocking_geocode(addr, **kw):
        stop_event.wait(timeout=5)
        return _GR(48.85, 2.35)
    monkeypatch.setattr("core.geocoder.geocode", _blocking_geocode)
    monkeypatch.setattr(
        "core.router.get_distance_matrix",
        lambda coords, **kw: [[0.0]],
    )

    controller = oc.OptimizeController(db=_StubDB())
    controller.start_geocode_then_optimize([oc.ParcelInput(id=1, address="X")])
    try:
        with pytest.raises(RuntimeError):
            controller.start_geocode_then_optimize(
                [oc.ParcelInput(id=2, address="Y")],
            )
    finally:
        stop_event.set()
        controller.cancel()
        if controller._worker:
            controller._worker.join(timeout=10)


def test_optimize_controller_infers_matrix_source_label():
    from ui.controllers.optimize_controller import OptimizeController
    # Asymmetric matrix → OSRM. A one-way street between stops forces
    # matrix[0][1] != matrix[1][0] which is impossible from Haversine math.
    one_way = [[0.0, 1200.0], [1500.0, 0.0]]
    assert "OSRM" in OptimizeController._infer_matrix_source(
        one_way, [(48.85, 2.35), (48.86, 2.34)],
    )

    # Perfectly symmetric small matrix → Haversine (great-circle math).
    symmetric = [[0.0, 320.0], [320.0, 0.0]]
    assert "Haversine" in OptimizeController._infer_matrix_source(
        symmetric, [(48.85, 2.35), (48.86, 2.34)],
    )

    # Floating-point noise within the 1 % epsilon → still Haversine.
    # NOTE: 0.005 / 1000.0 = 0.5e-5 ≪ 0.01 — safely under the threshold.
    epsilon_drift = [[0.0, 1000.0], [1000.005, 0.0]]
    assert "Haversine" in OptimizeController._infer_matrix_source(
        epsilon_drift, [(48.85, 2.35), (48.86, 2.34)],
    )

    # Very large symmetric Haversine values still classify as Haversine.
    # (Previously this case labelled as OSRM via the [200, 100_000] bounds;
    # the asymmetry heuristic is route-shape-based instead.) Coords are 1
    # degree of latitude apart (~111 km Haversine), matching the matrix.
    long_haversine = [[0.0, 111_000.0], [111_000.0, 0.0]]
    assert "Haversine" in OptimizeController._infer_matrix_source(
        long_haversine, [(48.85, 2.35), (49.85, 2.35)],
    )

    # 3x3 asymmetric matrix - the i<j loop must catch asymmetries between
    # any pair, not just (0, 1). Pair (1, 2) alone reveals the OSRM route.
    asym_3x3 = [
        [0.0, 1100.0, 2400.0],
        [1100.0, 0.0, 1500.0],   # asymmetric with [2][1] = 1900.0
        [2400.0, 1900.0, 0.0],
    ]
    assert "OSRM" in OptimizeController._infer_matrix_source(
        asym_3x3, [(48.85, 2.35), (48.86, 2.34), (48.87, 2.33)],
    )


# ---------------------------------------------------------------------------
# 4. location service — "RÉOPTIMISER D'ICI" (pure logic + off-device fallback)
# ---------------------------------------------------------------------------

def test_location_pick_fix_prefers_freshest_recent_candidate():
    from ui.services.location import _pick_fix
    now = 1_000_000
    candidates = [
        (now - 5000, 48.80, 2.20),     # 5 s old
        (now - 120_000, 48.90, 2.40),  # 2 min old
    ]
    assert _pick_fix(candidates, now_ms=now) == (48.80, 2.20)


def test_location_pick_fix_rejects_stale_and_malformed_entries():
    from ui.services.location import MAX_FIX_AGE_MS, _pick_fix
    now = 10_000_000
    candidates = [
        (now - MAX_FIX_AGE_MS - 1, 48.80, 2.20),  # too old
        (None, 48.85, 2.35),                      # no timestamp
        (now, None, 2.35),                        # no latitude
        (now,),                                   # truncated
        None,
    ]
    assert _pick_fix(candidates, now_ms=now) is None
    # ``max_age_ms=0`` disables the age filter (a fix just received).
    assert _pick_fix([(1, 48.80, 2.20)], now_ms=now, max_age_ms=0) == (48.80, 2.20)


def test_location_off_android_degrades_without_raising(monkeypatch):
    from ui.services import location
    monkeypatch.setattr(location, "_is_android", lambda: False)
    assert location.has_permission() is False
    assert location.request_permission(lambda granted: None) is False
    monkeypatch.setattr(location, "_post", lambda fn: fn())
    seen = {}
    started = location.request_position(
        lambda position, error: seen.update(position=position, error=error),
    )
    assert started is False
    assert seen["position"] is None
    assert seen["error"]


def test_location_best_known_fix_uses_fake_location_manager(monkeypatch):
    """``getLastKnownLocation`` reads every provider and keeps the newest."""
    from ui.services import location

    class _Loc:
        def __init__(self, stamp, lat, lon):
            self._stamp, self._lat, self._lon = stamp, lat, lon

        def getTime(self):
            return self._stamp

        def getLatitude(self):
            return self._lat

        def getLongitude(self):
            return self._lon

    class _Manager:
        def isProviderEnabled(self, name):
            return name != "passive"  # passive disabled by the OEM

        def getLastKnownLocation(self, name):
            return {
                "gps": _Loc(900_000, 48.70, 2.10),      # older
                "network": _Loc(999_000, 48.86, 2.35),  # freshest
            }[name]

    monkeypatch.setattr(location, "_location_manager", lambda: _Manager())
    monkeypatch.setattr(location, "_now_ms", lambda: 1_000_000)
    assert location._best_known_fix() == (48.86, 2.35)

    # A device whose caches are all stale must answer ``None`` (the screen
    # then keeps its manual "Départ" field instead of routing from nowhere).
    monkeypatch.setattr(location, "_now_ms", lambda: 9_999_999)
    assert location._best_known_fix() is None


def test_optimize_controller_start_point_only_keeps_every_stop(monkeypatch):
    """RÉOPTIMISER D'ICI: the GPS fix is fixed origin, all stops stay.

    Regression guard: the start point is a node of the distance matrix, so it
    must also be a node of the optimisation. Treating it as a bare index
    offset used to misalign indices (or silently drop the last stop).
    """
    from ui.controllers import optimize_controller as oc
    _patch_controller_for_test(monkeypatch, oc)

    geocoded_addresses = []

    class _GR:
        def __init__(self, lat, lon):
            self.lat, self.lon = lat, lon

    def _geocode(address, **kw):
        geocoded_addresses.append(address)
        return _GR(48.85, 2.35)

    monkeypatch.setattr("core.geocoder.geocode", _geocode)
    seen_coords = {}

    def _matrix(coords, **kw):
        seen_coords["coords"] = list(coords)
        n = len(coords)
        return [[0.0 if i == j else 10.0 for j in range(n)] for i in range(n)]

    monkeypatch.setattr("core.router.get_distance_matrix", _matrix)

    captured = {}
    controller = oc.OptimizeController(db=_StubDB())
    controller.bind(
        progress_cb=lambda *a: None,
        finished_cb=lambda r: captured.setdefault("finished", r),
        error_cb=lambda e: captured.setdefault("err", e),
    )
    controller.start_geocode_then_optimize(
        [oc.ParcelInput(id=1, address="A"), oc.ParcelInput(id=2, address="B")],
        start_point=oc.ParcelInput(id=-1, address="Ma position", lat=48.80, lon=2.20),
    )
    controller._worker.join(timeout=10)
    assert "err" not in captured, captured.get("err")
    result = captured["finished"]
    assert {p.id for p in result.ordered_parcels} == {1, 2}
    assert "Ma position" not in geocoded_addresses  # fix is not re-geocoded
    assert len(seen_coords["coords"]) == 3          # fix + 2 stops
    assert result.total_distance_m == 20.0          # two 10 m legs
    assert result.start_point is not None and result.end_point is None


def test_optimize_controller_error_callback_runs(monkeypatch):
    """When ``core.router.get_distance_matrix`` raises, ``error_cb`` fires."""
    from ui.controllers import optimize_controller as oc
    _patch_controller_for_test(monkeypatch, oc)
    monkeypatch.setattr(
        "core.geocoder.geocode",
        lambda addr, **kw: type("GR", (), {"lat": 48.85, "lon": 2.35})(),
    )
    def _boom(coords, **kw):
        raise RuntimeError("simulated network failure")
    monkeypatch.setattr("core.router.get_distance_matrix", _boom)

    controller = oc.OptimizeController(db=_StubDB())
    errs = {}
    controller.bind(
        progress_cb=lambda *a: None,
        finished_cb=lambda r: errs.setdefault("finished", r),
        error_cb=lambda e: errs.setdefault("err", e),
    )
    controller.start_geocode_then_optimize([oc.ParcelInput(id=1, address="X")])
    controller._worker.join(timeout=10)
    assert "err" in errs and not errs.get("finished")


# ---------------------------------------------------------------------------
# 5. tile_map — fond de carte OSM (assemblage, cache disque, repli hors ligne)
# ---------------------------------------------------------------------------

PARIS_STOPS = [
    (48.8566, 2.3522),   # Hôtel de Ville
    (48.8606, 2.3376),   # Louvre
    (48.8716, 2.3430),   # Gare de l'Est
]


def _png_bytes(size: int = 256, color=(210, 218, 226)) -> bytes:
    """A stand-in tile: real PNG bytes, so Pillow decodes them normally."""
    import io as _io
    from PIL import Image
    buf = _io.BytesIO()
    Image.new("RGB", (size, size), color).save(buf, format="PNG")
    return buf.getvalue()


def _stub_tiles(monkeypatch, tile_map):
    """Serve synthetic tiles: unit tests never touch the network."""
    def _fake_tile(z, x, y):
        import io as _io
        from PIL import Image
        buf = _io.BytesIO()
        Image.new("RGB", (256, 256), (210, 218, 226)).save(buf, format="PNG")
        return Image.open(_io.BytesIO(buf.getvalue())), False
    monkeypatch.setattr(tile_map, "_get_tile", _fake_tile)


def test_fit_zoom_is_finer_for_a_tighter_tour():
    from ui.services.tile_map import fit_zoom
    near = fit_zoom([(48.8566, 2.3522), (48.8570, 2.3530)], 900, 600)
    far = fit_zoom([(48.8566, 2.3522), (45.7640, 4.8357)], 900, 600)
    assert near > far >= 2


def test_fit_zoom_defaults_when_the_tour_is_a_single_point():
    from ui.services.tile_map import fit_zoom
    import config
    assert fit_zoom([(48.8566, 2.3522)], 900, 600) == config.Config.TILE_DEFAULT_ZOOM


def test_render_map_stitches_tiles_and_projects_each_stop(monkeypatch, tmp_path):
    from ui.services import tile_map
    monkeypatch.setattr(tile_map.config.Config, "CACHE_DIR", str(tmp_path))
    seen = []

    def _fake_tile(z, x, y):
        seen.append((z, x, y))
        return __import__("PIL.Image", fromlist=["Image"]).new("RGB", (256, 256), (210, 218, 226)), False

    monkeypatch.setattr(tile_map, "_get_tile", _fake_tile)
    render = tile_map.render_map(PARIS_STOPS, 900, 600)

    assert render is not None
    assert render.png[:8] == b"\x89PNG\r\n\x1a\n"
    assert render.tiles_total == len(seen) and render.tiles_total > 0
    assert render.tiles_fetched == render.tiles_total
    for lat, lon in PARIS_STOPS:
        fx, fy = render.project(lat, lon)
        assert 0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0
    # The western stop must land left of the eastern one, and the northern
    # stop above it (fraction 0 is the top of the canvas).
    assert render.project(48.8606, 2.3376)[0] < render.project(48.8716, 2.3430)[0]
    assert render.project(48.8716, 2.3430)[1] < render.project(48.8566, 2.3522)[1]


def test_render_map_returns_none_when_no_tile_is_available(monkeypatch, tmp_path):
    """Off-line the caller must keep its fallback, not show a white box."""
    from ui.services import tile_map
    monkeypatch.setattr(tile_map.config.Config, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(tile_map, "_get_tile", lambda z, x, y: None)
    assert tile_map.render_map(PARIS_STOPS, 900, 600) is None


def test_tiles_are_cached_on_disk_then_served_without_network(monkeypatch, tmp_path):
    from ui.services import tile_map
    monkeypatch.setattr(tile_map.config.Config, "CACHE_DIR", str(tmp_path))
    calls = []

    class _Response:
        content = _png_bytes()

        def raise_for_status(self):
            return None

    def _fake_get(url, **kwargs):
        calls.append(url)
        return _Response()

    monkeypatch.setattr(tile_map.requests, "get", _fake_get)

    first = tile_map.render_map(PARIS_STOPS, 400, 300)
    assert first is not None and len(calls) == first.tiles_total
    assert first.tiles_fetched == first.tiles_total

    downloaded = len(calls)
    second = tile_map.render_map(PARIS_STOPS, 400, 300)
    assert second is not None
    assert len(calls) == downloaded, "second render must not touch the network"
    assert second.tiles_fetched == 0
    assert second.zoom == first.zoom


def test_tile_request_carries_an_identifying_user_agent(monkeypatch, tmp_path):
    """The missing header is exactly what turned the tiles into a 403."""
    import config
    from ui.services import tile_map
    monkeypatch.setattr(tile_map.config.Config, "CACHE_DIR", str(tmp_path))
    sent = []

    class _Response:
        content = _png_bytes()

        def raise_for_status(self):
            return None

    def _fake_get(url, **kwargs):
        sent.append((url, kwargs.get("headers", {})))
        return _Response()

    monkeypatch.setattr(tile_map.requests, "get", _fake_get)
    tile_map.render_map(PARIS_STOPS, 400, 300)

    assert sent
    for url, headers in sent:
        assert headers["User-Agent"] == config.Config.TILE_USER_AGENT
        assert url.endswith(".png") and "tile.openstreetmap.org" in url


def test_tile_http_error_is_survivable(monkeypatch, tmp_path):
    """A 403/500 is a normal condition, never an exception to the UI."""
    from ui.services import tile_map
    monkeypatch.setattr(tile_map.config.Config, "CACHE_DIR", str(tmp_path))

    class _Response:
        content = b""

        def raise_for_status(self):
            raise RuntimeError("403 Forbidden")

    monkeypatch.setattr(tile_map.requests, "get", lambda url, **kwargs: _Response())
    assert tile_map.render_map(PARIS_STOPS, 400, 300) is None


def test_unproject_inverts_project(monkeypatch, tmp_path):
    """A pan gesture folds through unproject: it must land back on the point."""
    from ui.services import tile_map
    monkeypatch.setattr(tile_map.config.Config, "CACHE_DIR", str(tmp_path))
    _stub_tiles(monkeypatch, tile_map)
    render = tile_map.render_map(PARIS_STOPS, 900, 600, center=(48.8566, 2.3522))
    assert render is not None
    lat, lon = render.unproject(0.5, 0.5)
    assert abs(lat - 48.8566) < 1e-6 and abs(lon - 2.3522) < 1e-6
    for stop in PARIS_STOPS:
        fx, fy = render.project(*stop)
        back = render.unproject(fx, fy)
        assert abs(back[0] - stop[0]) < 1e-6 and abs(back[1] - stop[1]) < 1e-6


def test_fold_gesture_zooms_by_the_pinch_factor(monkeypatch, tmp_path):
    import config
    from ui.services import tile_map
    monkeypatch.setattr(tile_map.config.Config, "CACHE_DIR", str(tmp_path))
    _stub_tiles(monkeypatch, tile_map)
    render = tile_map.render_map(PARIS_STOPS, 900, 600, zoom=13, center=(48.8566, 2.3522))

    # Doubling the finger distance asks for one more zoom level.
    zoom, lat, lon = tile_map.fold_gesture(render, 0, 0, 2.0)
    assert zoom == 14 and abs(lat - 48.8566) < 1e-6

    # Zoom is clamped to the configured bounds, never off the tile pyramid.
    assert tile_map.fold_gesture(render, 0, 0, 64.0)[0] == config.Config.TILE_MAX_ZOOM
    assert tile_map.fold_gesture(render, 0, 0, 2.0 ** -20)[0] == config.Config.TILE_MIN_ZOOM
    # A pinch smaller than half a zoom level stays on the same level.
    assert tile_map.fold_gesture(render, 0, 0, 1.1)[0] == render.zoom


def test_fold_gesture_pans_the_centre_opposite_to_the_drag(monkeypatch, tmp_path):
    from ui.services import tile_map
    monkeypatch.setattr(tile_map.config.Config, "CACHE_DIR", str(tmp_path))
    _stub_tiles(monkeypatch, tile_map)
    render = tile_map.render_map(PARIS_STOPS, 900, 600, zoom=13, center=(48.8566, 2.3522))

    # Dragging the map to the right reveals what was on its left: the new
    # centre must move west (smaller longitude).
    _, _, lon_west = tile_map.fold_gesture(render, dx=200, dy=0, live_scale=1.0)
    _, _, lon_east = tile_map.fold_gesture(render, dx=-200, dy=0, live_scale=1.0)
    assert lon_west < 2.3522 < lon_east
    # Dragging upwards reveals what was below: the centre moves south.
    lat_south, _, _ = tile_map.fold_gesture(render, dx=0, dy=200, live_scale=1.0)
    assert lat_south < 48.8566


def test_explicit_zoom_and_center_drive_the_tiles(monkeypatch, tmp_path):
    """Zooming must actually change which tiles are requested."""
    from ui.services import tile_map
    monkeypatch.setattr(tile_map.config.Config, "CACHE_DIR", str(tmp_path))
    asked = []
    _stub_tiles(monkeypatch, tile_map)
    inner = tile_map._get_tile

    def _recording_tile(z, x, y):
        asked.append((z, x, y))
        return inner(z, x, y)

    monkeypatch.setattr(tile_map, "_get_tile", _recording_tile)
    tile_map.render_map(PARIS_STOPS, 400, 300, zoom=12, center=(48.8566, 2.3522))
    zooms = {z for z, _, _ in asked}
    assert zooms == {12}

    asked.clear()
    tile_map.render_map(PARIS_STOPS, 400, 300, zoom=15, center=(48.8566, 2.3522))
    assert {z for z, _, _ in asked} == {15}
