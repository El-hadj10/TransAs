"""Unit tests for ``core.optimizer``.

Includes a performance regression test: ``test_optimize_under_1_5_seconds_for_300_stops``
guards the mobile-CPU budget calibrated in structure.md Step 1.4.
"""
import random
import time

import pytest

from core import optimizer


# ---------------------------------------------------------------------------
# Synthetic data helpers
# ---------------------------------------------------------------------------

def _make_stops(n: int, seed: int = 42,
                lat_range=(48.80, 49.00), lon_range=(2.20, 2.50)) -> list:
    """Generate n random stops in a Paris-ish bounding box."""
    rng = random.Random(seed)
    return [
        {"id": i, "lat": lat_range[0] + rng.random() * (lat_range[1] - lat_range[0]),
         "lon": lon_range[0] + rng.random() * (lon_range[1] - lon_range[0])}
        for i in range(n)
    ]


def _random_symmetric_matrix(n: int, seed: int = 42, scale: float = 100.0) -> list:
    """Symmetric distance matrix in ``[0, scale]``."""
    rng = random.Random(seed)
    m = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            d = rng.random() * scale
            m[i][j] = d
            m[j][i] = d
    return m


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_optimize_empty_returns_empty():
    assert optimizer.optimize([], []) == []


def test_optimize_single_stop_returns_zero():
    stops = [{"id": 0, "lat": 48.85, "lon": 2.35}]
    assert optimizer.optimize(stops, [[0.0]]) == [0]


def test_optimize_small_uses_nn_plus_twoopt_directly():
    stops = _make_stops(5)
    matrix = _random_symmetric_matrix(5, seed=1)
    route = optimizer.optimize(stops, matrix, start=0)
    assert sorted(route) == [0, 1, 2, 3, 4]
    assert route[0] == 0


def test_two_opt_improves_or_equals_nn():
    stops = _make_stops(20)
    matrix = _random_symmetric_matrix(20, seed=7)
    nn_route = optimizer.nearest_neighbor(matrix, start=0)
    nn_dist = optimizer.route_distance(nn_route, matrix)
    opt_route = list(nn_route)
    optimizer.two_opt(opt_route, matrix)
    opt_dist = optimizer.route_distance(opt_route, matrix)
    assert opt_dist <= nn_dist + 1e-9


def test_route_distance_zero_for_single_or_empty():
    assert optimizer.route_distance([], []) == 0.0
    assert optimizer.route_distance([0], [[0.0]]) == 0.0


def test_kmeans_returns_every_index_exactly_once():
    stops = _make_stops(60, seed=11)
    clusters = optimizer.kmeans_cluster(stops, k=3)
    flat = [i for c in clusters for i in c]
    assert sorted(flat) == list(range(len(stops)))


def test_kmeans_k_for_chooses_reasonable_k():
    assert optimizer.kmeans_k_for(n=10, max_per=30, min_k=3) == 3
    assert optimizer.kmeans_k_for(n=90, max_per=30, min_k=3) == 3
    assert optimizer.kmeans_k_for(n=120, max_per=30, min_k=3) == 4
    assert optimizer.kmeans_k_for(n=300, max_per=30, min_k=3) == 10


def test_optimize_start_is_always_first_for_many_volumes():
    for n in (10, 41, 80, 150):
        stops = _make_stops(n, seed=n)
        matrix = _random_symmetric_matrix(n, seed=n)
        start = 17 % n
        route = optimizer.optimize(stops, matrix, start=start)
        assert sorted(route) == list(range(n)), f"missing indices for n={n}"
        assert route[0] == start, f"start must be first for n={n}"


def test_optimize_under_1_5_seconds_for_300_stops():
    """Mobile-CPU budget regression test (cf. structure.md Step 1.4)."""
    stops = _make_stops(300, seed=2024)
    matrix = _random_symmetric_matrix(300, seed=2024)
    t0 = time.perf_counter()
    route = optimizer.optimize(stops, matrix, start=0)
    elapsed = time.perf_counter() - t0
    assert sorted(route) == list(range(300))
    assert elapsed < 1.5, f"optimize took {elapsed:.3f}s (> 1.5s budget)"


def test_optimize_invalid_start_raises():
    stops = _make_stops(5)
    matrix = _random_symmetric_matrix(5)
    with pytest.raises(IndexError):
        optimizer.optimize(stops, matrix, start=42)


def test_optimize_raises_when_kmeans_drops_indices(monkeypatch):
    """If ``kmeans_cluster`` returns a partition that drops a stop or
    duplicates one, ``optimize`` must surface a ``RuntimeError`` so the
    bug surfaces loudly (and not silently produce a shorter / wrong route).
    """
    stops = _make_stops(50, seed=3)
    matrix = _random_symmetric_matrix(50, seed=3)

    def broken_kmeans(stops_, k, **kwargs):
        # Drop stop 7 from cluster 0, and have a second cluster that
        # re-introduces stop 7 along with stop 3 — producing a duplicate.
        idxs_a = [i for i in range(len(stops_)) if i != 7]
        idxs_b = [3, 7]
        return [idxs_a, idxs_b]

    monkeypatch.setattr(optimizer, "kmeans_cluster", broken_kmeans)

    with pytest.raises(RuntimeError):
        optimizer.optimize(stops, matrix, start=0)


def test_optimize_raises_when_kmeans_skips_start(monkeypatch):
    """If no cluster contains the requested start, the runner must fail
    rather than silently pick a different start."""
    stops = _make_stops(60, seed=8)
    matrix = _random_symmetric_matrix(60, seed=8)
    start = 27  # the drops remove index 27 from any cluster

    def missing_start_kmeans(stops_, k, **kwargs):
        # Three clusters, but the start index (27) is excluded from all.
        idxs_a = list(range(0, 20))
        idxs_b = list(range(20, 27)) + list(range(28, 40))
        idxs_c = list(range(40, 60))
        return [idxs_a, idxs_b, idxs_c]

    monkeypatch.setattr(optimizer, "kmeans_cluster", missing_start_kmeans)

    with pytest.raises(RuntimeError):
        optimizer.optimize(stops, matrix, start=start)
