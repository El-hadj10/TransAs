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

# Project root on sys.path (mirrors ``conftest.py``).
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


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
    # Small symmetric matrix → Haversine.
    small = [[0.0, 320.0], [320.0, 0.0]]
    assert "Haversine" in OptimizeController._infer_matrix_source(
        small, [(48.85, 2.35), (48.86, 2.34)],
    )
    # Out-of-band values → OSRM.
    giant = [[0.0, 200_000.0], [200_000.0, 0.0]]
    assert "OSRM" in OptimizeController._infer_matrix_source(
        giant, [(48.85, 2.35), (48.86, 2.34)],
    )


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
