"""Async controller between the UI thread and ``core/`` + ``database/``.

Why this exists: Kivy only allows widget-tree mutations from the main
thread, so Nominatim (1 req/s, slow), OSRM (cluster-by-cluster calls)
and ``core.optimizer.optimize`` (CPU-bound but sub-second) cannot
block the UI. We encapsulate the whole optimise flow in a single
:class:`OptimizeController` that exposes:

  * ``start_geocode_then_optimize(parcels)``  — kicks off a worker thread.
  * ``bind(progress_cb=..., finished_cb=..., error_cb=...)``
    — Kivy-friendly threading-safe subscribers.
  * ``is_running`` flag for "Optimiser" button toggling.
  * Cooperative ``cancel()`` (flag the worker checks at every step).

All UI-facing emissions go through Kivy ``Clock.schedule_once`` so
subscribers always run on the main thread (lazy import keeps the
module importable headless for tests).
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, List, Optional, Sequence

import config
from core import geocoder, router, optimizer
from database import db_manager

_logger = logging.getLogger("transas.ui.optimize_controller")


@dataclass
class ParcelInput:
    """Minimum input shape needed to start an optimize flow."""
    id: int
    address: str
    lat: Optional[float] = None
    lon: Optional[float] = None


@dataclass
class OptimizeResult:
    """Aggregated output of one successful optimisation run."""
    ordered_parcels: List[ParcelInput] = field(default_factory=list)
    total_distance_m: float = 0.0
    matrix_source: str = "Haversine"   # "OSRM" or "Haversine"
    start_point: Optional[ParcelInput] = None
    end_point: Optional[ParcelInput] = None


# Callback signatures — widened on 2026-07 to expose the ``label`` arg
# (the previously discarded stage announcement).
ProgressCB = Callable[[int, int, str], None]
FinishedCB = Callable[[OptimizeResult], None]
ErrorCB = Callable[[BaseException], None]


class OptimizeController:
    """Coordinator for the address → optimised order pipeline."""

    def __init__(self, db: Optional[db_manager.DBManager] = None):
        self._db = db or db_manager.DBManager()
        self._cancel_event = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self.is_running: bool = False

        self._on_progress: Optional[ProgressCB] = None
        self._on_finished: Optional[FinishedCB] = None
        self._on_error: Optional[ErrorCB] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def bind(
        self,
        *,
        progress_cb: Optional[ProgressCB] = None,
        finished_cb: Optional[FinishedCB] = None,
        error_cb: Optional[ErrorCB] = None,
    ) -> None:
        self._on_progress = progress_cb
        self._on_finished = finished_cb
        self._on_error = error_cb

    def start_geocode_then_optimize(
        self, parcels: Sequence[ParcelInput], *,
        start_point: Optional[ParcelInput] = None,
        end_point: Optional[ParcelInput] = None,
    ) -> None:
        if self.is_running:
            raise RuntimeError("OptimizeController: a run is already in progress")
        if not parcels:
            raise ValueError("OptimizeController.start_geocode_then_optimize: empty input")

        self._cancel_event = threading.Event()
        self.is_running = True
        thread = threading.Thread(
            target=self._run_pipeline,
            args=(list(parcels), start_point, end_point),
            name="transas.optimize_worker",
            daemon=True,
        )
        self._worker = thread
        thread.start()

    def cancel(self) -> None:
        self._cancel_event.set()
        _logger.info("OptimizeController: cancel requested")

    # ------------------------------------------------------------------
    # Worker thread body
    # ------------------------------------------------------------------

    def _run_pipeline(self, parcels: List[ParcelInput],
                      start_point: Optional[ParcelInput] = None,
                      end_point: Optional[ParcelInput] = None) -> None:
        try:
            # ---- Step 1: geocode pending parcels -----------------
            self._emit_progress(0, len(parcels), "Géocodage…")
            geocoded: List[ParcelInput] = []
            for i, p in enumerate(parcels, start=1):
                if self._cancel_event.is_set():
                    _emit_main_thread(self._on_error, RuntimeError("Annulé par l'utilisateur"))
                    return
                if p.lat is not None and p.lon is not None:
                    geocoded.append(p)
                    self._emit_progress(i, len(parcels), "Géocodage…")
                    continue
                result = geocoder.geocode(p.address)
                if result is None:
                    _logger.warning(
                        "Geocode failed for parcel %d (%r) — kept as un-geocoded",
                        p.id, p.address,
                    )
                    geocoded.append(p)  # lat/lon remain None
                else:
                    try:
                        self._db.update_parcel_coords(p.id, result.lat, result.lon)
                    except Exception:
                        _logger.exception(
                            "Failed to backfill coords for parcel %d", p.id,
                        )
                    p.lat = result.lat
                    p.lon = result.lon
                    geocoded.append(p)
                self._emit_progress(i, len(parcels), "Géocodage…")

            routable = [p for p in geocoded if p.lat is not None and p.lon is not None]
            unrouted = [p for p in geocoded if p not in routable]
            if not routable:
                _emit_main_thread(
                    self._on_error,
                    RuntimeError("Aucun colis géocodable — vérifier les adresses"),
                )
                return

            for label, point in (("Départ", start_point), ("Arrivée", end_point)):
                if point is None or (point.lat is not None and point.lon is not None):
                    continue
                self._emit_progress(len(parcels), len(parcels), f"Géocodage {label.lower()}…")
                result = geocoder.geocode(point.address)
                if result is None:
                    _emit_main_thread(self._on_error, RuntimeError(f"{label} introuvable : {point.address}"))
                    return
                point.lat, point.lon = result.lat, result.lon

            # ---- Step 2: build distance matrix --------------------
            self._emit_progress(len(parcels), len(parcels), "Matrice des distances…")
            route_points = ([] if start_point is None else [start_point]) + routable + ([] if end_point is None else [end_point])
            coords = [(p.lat, p.lon) for p in route_points]  # type: ignore[arg-type]
            matrix = router.get_distance_matrix(coords)
            source = self._infer_matrix_source(matrix, coords)
            self._emit_progress(len(parcels), len(parcels), "Optimisation…")

            # ---- Step 3: optimise --------------------------------
            start_index = 0 if start_point is not None else None
            end_index = len(route_points) - 1 if end_point is not None else None
            stops = [{"id": p.id, "lat": p.lat, "lon": p.lon} for p in route_points]
            if start_index is not None and end_index is not None:
                full_order = optimizer.optimize_open_path(
                    matrix, start=start_index, end=end_index,
                )
            elif start_index is not None:
                # "RÉOPTIMISER D'ICI": the driver's position is the fixed
                # origin and every pending stop is free. The start point is a
                # real node of the matrix, so it must also be a node of the
                # optimisation — previously it was used as a bare index offset
                # over a matrix that contained it, which misaligned every
                # subsequent index and could drop a stop from the route.
                full_order = optimizer.optimize(stops, matrix, start=start_index)
            elif end_index is not None:
                # Return point only: optimise an open path that ends there,
                # with the first pending stop as the free origin.
                full_order = optimizer.optimize_open_path(
                    matrix, start=0, end=end_index,
                )
            else:
                full_order = optimizer.optimize(stops, matrix, start=0)
            fixed = {index for index in (start_index, end_index) if index is not None}
            ordered_routable = [
                route_points[index] for index in full_order if index not in fixed
            ]
            total = optimizer.route_distance(full_order, matrix)
            final = ordered_routable + unrouted

            # ---- Step 4: persist tour ------------------------
            date_str = datetime.now().date().isoformat()
            ordered_ids = [p.id for p in final]
            self._db.save_tour(date_str, ordered_ids)

            result = OptimizeResult(
                ordered_parcels=final,
                total_distance_m=total,
                matrix_source=source,
                start_point=start_point,
                end_point=end_point,
            )
            self._emit_progress(len(parcels), len(parcels), "Terminé ✓")
            _emit_main_thread(self._on_finished, result)
        except BaseException as exc:  # noqa: BLE001 — last-resort surface
            _logger.exception("Optimize pipeline crashed")
            _emit_main_thread(self._on_error, exc)
        finally:
            self.is_running = False

    @staticmethod
    def _infer_matrix_source(matrix, coords) -> str:
        """Cheap discriminator: OSRM road-distance matrices are not symmetric
        (one-way streets, ramps) while Haversine great-circle matrices are
        exactly symmetric (rounding within ``1 %`` of the larger leg).

        Falling back to "Haversine" on a perfectly symmetric OSRM matrix
        (e.g. an all-two-way route through a small village) is acceptable:
        the UI label only drives the status-bar badge, not behavior, and the
        false-positive direction (a real Haversine matrix labeled "OSRM")
        is what the original bounds heuristic [200, 100_000] produced too
        often on adjacent urban stops.

        Degenerate case (all-zero / all-None matrix) silently returns
        "Haversine" since every cell is skipped; router.py never
        produces such a matrix in practice. NaN cells are also silently
        treated as Haversine (IEEE 754 NaN comparisons always return
        False); OSRM responses should not contain NaN.
        """
        if not matrix or len(matrix) < 2:
            return "Haversine"
        n = len(matrix)
        for i in range(n):
            for j in range(i + 1, n):
                a, b = matrix[i][j], matrix[j][i]
                if a is None or b is None or a <= 0 or b <= 0:
                    continue
                if abs(a - b) > 0.01 * max(a, b):
                    return "OSRM"
        return "Haversine"

    # ------------------------------------------------------------------
    # Thread-safe emission helpers
    # ------------------------------------------------------------------

    def _emit_progress(self, done: int, total: int, label: str) -> None:
        cb = self._on_progress
        if cb is None:
            return
        try:
            from kivy.clock import Clock
        except ImportError:
            cb(done, total, label)  # fallback headless / CI
            return
        Clock.schedule_once(lambda _dt: cb(done, total, label), 0)


def _emit_main_thread(cb: Optional[Callable], *args) -> None:
    """Hop onto the Kivy main thread if available (else direct call)."""
    if cb is None:
        return
    try:
        from kivy.clock import Clock
        Clock.schedule_once(lambda _dt: cb(*args), 0)
    except ImportError:
        cb(*args)
