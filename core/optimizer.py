"""Hierarchical TSP optimization.

Pipeline (chosen for >100 stops on Android — see structure.md Step 1.4):

    1. If len(stops) <= OPTIMIZER_SMALL_LIMIT (40):
         nearest_neighbor(start=start) + 2-opt.
    2. Else:
       a. kmeans_cluster(stops, K=ceil(N/30), K>=3, K-means++ seeding).
       b. Order clusters by nearest_neighbor on centroid distances.
       c. Optimize intra-cluster routes with NN + 2-opt on the
          OSRM road-distance sub-matrix.
       d. Rotate the start stop to position 0; concatenate.

Public API:
    * :func:`optimize`            — reorder indices for delivery.
    * :func:`nearest_neighbor`    — greedy route from a distance matrix.
    * :func:`two_opt`             — local 2-opt improvement.
    * :func:`kmeans_cluster`      — K-Means with K-means++ seeding.
"""
from __future__ import annotations

import math
import random
from typing import Dict, List, Sequence, Tuple

import config


# A delivery stop is a dict: {"id": <hashable>, "lat": float, "lon": float}
Stop = Dict[str, object]


# ---------------------------------------------------------------------------
# Distance helpers (engineered to be allocation-light)
# ---------------------------------------------------------------------------

def _sq_latlon(a: Stop, b: Stop) -> float:
    """Squared Euclidean distance in raw lat/lon space (for K-Means)."""
    return (float(a["lat"]) - float(b["lat"])) ** 2 + \
           (float(a["lon"]) - float(b["lon"])) ** 2


def route_distance(route: Sequence[int], matrix: Sequence[Sequence[float]]) -> float:
    """Sum of consecutive distances along ``route``. Open-path (not closed)."""
    return sum(matrix[route[i]][route[i + 1]] for i in range(len(route) - 1))


# ---------------------------------------------------------------------------
# NN + 2-opt (small-volume path + intra-cluster step)
# ---------------------------------------------------------------------------

def nearest_neighbor(matrix: Sequence[Sequence[float]], start: int = 0) -> List[int]:
    """Greedy nearest-neighbour route starting at ``start``."""
    n = len(matrix)
    if n == 0:
        return []
    visited = [False] * n
    route = [start]
    visited[start] = True
    row = matrix[start]
    for _ in range(n - 1):
        best_j = -1
        best_d = math.inf
        for j in range(n):
            if not visited[j] and row[j] < best_d:
                best_d = row[j]
                best_j = j
        route.append(best_j)
        visited[best_j] = True
        row = matrix[best_j]
    return route


def two_opt(route: List[int], matrix: Sequence[Sequence[float]],
            max_iterations: int = 50) -> List[int]:
    """Classic 2-opt. Mutates ``route`` in place and returns it.

    Iterates until no improving swap is found, capped by ``max_iterations``
    to guarantee a finite runtime on adversarial inputs.
    """
    n = len(route)
    if n < 4:
        return route

    improved = True
    for _ in range(max_iterations):
        improved = False
        for i in range(1, n - 2):
            for j in range(i + 1, n - 1):
                a, b = route[i - 1], route[i]
                c, d = route[j], route[j + 1]
                delta = matrix[a][c] + matrix[b][d] - matrix[a][b] - matrix[c][d]
                if delta < -1e-9:
                    route[i:j + 1] = reversed(route[i:j + 1])
                    improved = True
        if not improved:
            break
    return route


# ---------------------------------------------------------------------------
# K-Means clustering with K-means++ seeding
# ---------------------------------------------------------------------------

def kmeans_cluster(stops: Sequence[Stop], k: int,
                   max_iter: int = 30, seed: int = 1234) -> List[List[int]]:
    """Pure-Python K-Means (K-means++ init, Lloyd's loop). Returns index lists.

    Each input index appears in exactly one returned cluster. Empty clusters
    are skipped (the final return is compacted to non-empty lists).
    Deterministic via the ``seed`` argument.

    Convergence threshold is intentionally loose (``1e-4`` in squared
    lat/lon space) because Paris-area lat/lon values cluster in ~0.1–0.5
    and a microscopic threshold would just burn max_iter cycles for nothing.
    """
    n = len(stops)
    if n == 0:
        return []
    k = max(1, min(k, n))

    rng = random.Random(seed)
    # K-means++: pick the first centroid uniformly at random, then sample
    # subsequent ones with probability ∝ squared distance from the nearest
    # already-chosen centroid.
    first = rng.randrange(n)
    centroids: List[Tuple[float, float]] = [
        (float(stops[first]["lat"]), float(stops[first]["lon"]))
    ]
    while len(centroids) < k:
        weights = [
            min((c[0] - float(s["lat"])) ** 2 + (c[1] - float(s["lon"])) ** 2
                for c in centroids)
            for s in stops
        ]
        total = sum(weights)
        if total <= 0.0:
            centroids.append(
                (float(stops[rng.randrange(n)]["lat"]), float(stops[rng.randrange(n)]["lon"]))
            )
            continue
        target = rng.random() * total
        cum = 0.0
        for s, w in zip(stops, weights):
            cum += w
            if cum >= target:
                centroids.append((float(s["lat"]), float(s["lon"])))
                break

    cluster_indices: List[List[int]] = [[] for _ in range(k)]
    for _ in range(max_iter):
        for lst in cluster_indices:
            lst.clear()

        for idx, s in enumerate(stops):
            best_c = 0
            best_d = math.inf
            for ci, c in enumerate(centroids):
                d = (c[0] - float(s["lat"])) ** 2 + (c[1] - float(s["lon"])) ** 2
                if d < best_d:
                    best_d = d
                    best_c = ci
            cluster_indices[best_c].append(idx)

        new_centroids: List[Tuple[float, float]] = list(centroids)
        for ci, idxs in enumerate(cluster_indices):
            if not idxs:
                continue
            mean_lat = sum(float(stops[i]["lat"]) for i in idxs) / len(idxs)
            mean_lon = sum(float(stops[i]["lon"]) for i in idxs) / len(idxs)
            # Re-anchor centroid to the nearest real stop to keep downstream
            # centroid distance comparisons numerically stable.
            rep = min(idxs, key=lambda i: (float(stops[i]["lat"]) - mean_lat) ** 2
                                       + (float(stops[i]["lon"]) - mean_lon) ** 2)
            new_centroids[ci] = (float(stops[rep]["lat"]), float(stops[rep]["lon"]))

        shift = sum(
            (new_centroids[i][0] - centroids[i][0]) ** 2
            + (new_centroids[i][1] - centroids[i][1]) ** 2
            for i in range(k)
        )
        centroids = new_centroids
        if shift < 1e-4:
            break

    return [lst for lst in cluster_indices if lst]


def kmeans_k_for(n: int, max_per: int, min_k: int) -> int:
    """Choose K as ``ceil(n / max_per)`` clamped to ``[1, n]`` and ``>= min_k``."""
    if n <= 1:
        return 1
    raw = -(-n // max_per)  # ceil
    return max(min_k, min(raw, n))


# ---------------------------------------------------------------------------
# Top-level optimization pipeline
# ---------------------------------------------------------------------------

def _centroid(stops: Sequence[Stop], indices: Sequence[int]) -> Tuple[float, float]:
    return (
        sum(float(stops[i]["lat"]) for i in indices) / len(indices),
        sum(float(stops[i]["lon"]) for i in indices) / len(indices),
    )


def _build_euclid_matrix(points: Sequence[Tuple[float, float]]) -> List[List[float]]:
    n = len(points)
    return [
        [math.hypot(points[i][0] - points[j][0], points[i][1] - points[j][1])
         for j in range(n)]
        for i in range(n)
    ]


def _optimize_small(stops: Sequence[Stop], matrix: Sequence[Sequence[float]],
                    cluster: Sequence[int], local_start: int) -> List[int]:
    """Optimize the route over a single cluster. Rotates ``local_start`` to 0."""
    n = len(cluster)
    if n == 0:
        return []
    if n == 1:
        return [cluster[0]]
    sub_matrix = [[matrix[i][j] for j in cluster] for i in cluster]
    local_start = max(0, min(local_start, n - 1))
    route = nearest_neighbor(sub_matrix, start=local_start)
    two_opt(route, sub_matrix)
    pos = route.index(local_start)
    if pos != 0:
        route = route[pos:] + route[:pos]
    return [cluster[i] for i in route]


def optimize(stops: Sequence[Stop], matrix: Sequence[Sequence[float]],
             start: int = 0,
             *,
             max_per_cluster: int = None,
             min_clusters: int = None,
             small_limit: int = None) -> List[int]:
    """Return the optimized original-index order. Caller owns the matrix.

    The returned list starts with ``start`` and contains every input index
    exactly once.

    Args:
        stops: List of ``{"id": ..., "lat": ..., "lon": ...}`` dicts.
        matrix: NxN distance matrix, ``matrix[i][j]`` is the road distance
                from stop ``i`` to stop ``j`` in meters.
        start: Index of the starting stop (typically the depot).
        max_per_cluster, min_clusters, small_limit: overrides for the
                matching ``config.Config.OPTIMIZER_*`` knobs (mostly for tests).
    """
    n = len(stops)
    if n == 0:
        return []
    if n == 1:
        return [0]
    if start < 0 or start >= n:
        raise IndexError(f"start index {start} out of range for {n} stops")

    small_limit = small_limit if small_limit is not None else config.Config.OPTIMIZER_SMALL_LIMIT
    max_per_cluster = max_per_cluster if max_per_cluster is not None \
        else config.Config.OPTIMIZER_MAX_STOPS_PER_CLUSTER
    min_clusters = min_clusters if min_clusters is not None \
        else config.Config.OPTIMIZER_MIN_CLUSTERS

    if n <= small_limit:
        route = nearest_neighbor(matrix, start=start)
        two_opt(route, matrix)
        pos = route.index(start)
        return route[pos:] + route[:pos]

    # ----- Hierarchical path --------------------------------------------------
    k = kmeans_k_for(n, max_per_cluster, min_clusters)
    clusters = kmeans_cluster(stops, k=k)

    if len(clusters) <= 1:
        # Degenerate case (e.g. all stops share coordinates) — fall back to NN.
        route = nearest_neighbor(matrix, start=start)
        two_opt(route, matrix)
        pos = route.index(start)
        return route[pos:] + route[:pos]

    centroid_points = [_centroid(stops, ci) for ci in clusters]
    cmatrix = _build_euclid_matrix(centroid_points)
    start_cluster = next(
        (i for i, ci in enumerate(clusters) if start in ci),
        0,
    )
    cluster_order = nearest_neighbor(cmatrix, start=start_cluster)
    two_opt(cluster_order, cmatrix)

    final_route: List[int] = []
    for ci in cluster_order:
        cl = clusters[ci]
        local_start = cl.index(start) if start in cl else 0
        final_route.extend(_optimize_small(stops, matrix, cl, local_start))

    # Public invariants: every input index appears exactly once and the start
    # is at position 0. Raised as RuntimeError so they survive `python -O`.
    if len(final_route) != n:
        raise RuntimeError(
            f"optimize invariant broken: expected {n} stops, got {len(final_route)}"
        )
    if sorted(final_route) != list(range(n)):
        raise RuntimeError("optimize invariant broken: missing or duplicated indices")
    if final_route[0] != start:
        raise RuntimeError(
            f"optimize invariant broken: expected start={start} at position 0, "
            f"found {final_route[0]}"
        )
    return final_route
