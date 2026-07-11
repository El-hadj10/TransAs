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

    def start_geocode_then_optimize(self, parcels: Sequence[ParcelInput]) -> None:
        if self.is_running:
            raise RuntimeError("OptimizeController: a run is already in progress")
        if not parcels:
            raise ValueError("OptimizeController.start_geocode_then_optimize: empty input")

        self._cancel_event = threading.Event()
        self.is_running = True
        thread = threading.Thread(
            target=self._run_pipeline,
            args=(list(parcels),),
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

    def _run_pipeline(self, parcels: List[ParcelInput]) -> None:
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

            # ---- Step 2: build distance matrix --------------------
            self._emit_progress(len(parcels), len(parcels), "Matrice des distances…")
            coords = [(p.lat, p.lon) for p in routable]  # type: ignore[arg-type]
            matrix = router.get_distance_matrix(coords)
            source = self._infer_matrix_source(matrix, coords)
            self._emit_progress(len(parcels), len(parcels), "Optimisation…")

            # ---- Step 3: optimise --------------------------------
            stops = [{"id": p.id, "lat": p.lat, "lon": p.lon} for p in routable]
            order = optimizer.optimize(stops, matrix, start=0)
            ordered_routable = [routable[i] for i in order]
            final = ordered_routable + unrouted

            # ---- Step 4: persist tour ------------------------
            date_str = datetime.now().date().isoformat()
            ordered_ids = [p.id for p in final]
            self._db.save_tour(date_str, ordered_ids)

            total = sum(
                matrix[order[i]][order[i + 1]] for i in range(len(order) - 1)
            )

            result = OptimizeResult(
                ordered_parcels=final,
                total_distance_m=total,
                matrix_source=source,
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
        """Cheap heuristic: a single off-diagonal value outside [200, 100000]
        meters is impossible for a Haversine great-circle calculation on
        adjacent urban stops ⇒ matrix came from OSRM."""
        if not matrix or len(matrix) < 2:
            return "Haversine"
        n = len(matrix)
        # Sample a wider spread than the previous 3×3 top-left for diversity.
        sample_pairs = [
            (0, min(1, n - 1)),
            (0, min(n // 2, n - 1)),
            (min(n // 2, n - 1), n - 1),
        ]
        for i, j in sample_pairs:
            if i == j:
                continue
            v = matrix[i][j]
            if v is None or v <= 0:
                continue
            if v < 200 or v > 100_000:
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
