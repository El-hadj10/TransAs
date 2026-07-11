"""OSRM-backed distance/duration matrix with Haversine fallback.

Single entry point: :func:`get_distance_matrix`. The OSRM public demo
endpoint is flaky and rate-limited, so retries are mandatory and a pure
Haversine fallback keeps the rest of the pipeline alive when offline.
"""
from __future__ import annotations

import logging
import math
from typing import List, Optional, Sequence, Tuple

import requests

import config

# Module-level logger for fallback and rate-limit diagnostics.
# Defined once at import so callers can `logging.basicConfig(level=…)`
# to control verbosity; we never print to stdout/stderr directly.
_logger = logging.getLogger("transas.core.router")


class OSRMError(RuntimeError):
    """Raised when OSRM returns a non-``Ok`` code or an unusable payload."""


Coord = Tuple[float, float]  # (lat, lon)


def coordinates_to_path(coords: Sequence[Coord]) -> str:
    """Convert ``[(lat, lon), ...]`` to the ``{lon,lat;lon,lat;...}`` OSRM path."""
    return ";".join(f"{lon},{lat}" for lat, lon in coords)


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points in meters."""
    earth_radius = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    return 2 * earth_radius * math.asin(math.sqrt(a))


def haversine_matrix(coords: Sequence[Coord]) -> List[List[float]]:
    """Public alias of the Haversine fallback matrix.

    Exposed publicly because the rest of the pipeline relies on it when OSRM
    is unreachable, and so callers (and tests) can request it directly.
    """
    n = len(coords)
    return [
        [
            0.0 if i == j else haversine_distance(coords[i][0], coords[i][1],
                                                  coords[j][0], coords[j][1])
            for j in range(n)
        ]
        for i in range(n)
    ]


def get_distance_matrix(
    coords: Sequence[Coord],
    *,
    retries: Optional[int] = None,
    timeout: Optional[int] = None,
) -> List[List[float]]:
    """Return an NxN road distance matrix (meters).

    Args:
        coords: List of ``(lat, lon)`` tuples (≥ 0).
        retries: Max OSRM attempts before falling back to Haversine.
                 Defaults to ``Config.OSRM_MAX_RETRIES``.
        timeout: Per-request timeout in seconds. Defaults to
                 ``Config.OSRM_TIMEOUT_SEC``.

    Returns:
        Square matrix with ``matrix[i][j]`` the distance from ``coords[i]``
        to ``coords[j]`` in meters. Falls back to straight-line Haversine
        if all retries are exhausted.
    """
    n = len(coords)
    if n == 0:
        return []
    if n == 1:
        return [[0.0]]

    retries = retries if retries is not None else config.Config.OSRM_MAX_RETRIES
    timeout = timeout if timeout is not None else config.Config.OSRM_TIMEOUT_SEC

    if retries < 1:
        return haversine_matrix(coords)

    url = f"{config.Config.OSRM_URL}/table/v1/driving/{coordinates_to_path(coords)}"
    params = {"annotations": "distance"}
    # 3.05s connect (TCP + TLS handshake) + `timeout` read, with explicit
    # ``verify=True`` so the TLS chain is always verified against the
    # platform trust store (defense-in-depth against a runtime that flips
    # the requests default).
    request_timeout: tuple = (3.05, timeout)

    last_exc: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=request_timeout,
                verify=True,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != "Ok":
                raise OSRMError(f"OSRM returned code={payload.get('code')!r}")
            distances = payload["distances"]
            if distances is None:
                raise OSRMError("OSRM returned null distances (unreachable points?)")
            return distances
        except (requests.RequestException, OSRMError, ValueError, OSError) as exc:
            # ``OSError`` covers the built-in ``ConnectionError`` (and any
            # raw socket-layer fault that the ``requests`` library doesn't
            # wrap). The only operations between this point and the request
            # are string formatting (``coordinates_to_path``) and a single
            # ``requests.get`` call, so an ``OSError`` reaching here is
            # essentially always a transport-level failure — never a
            # programmer error such as ``KeyError`` or ``AttributeError``.
            # We therefore fall back to Haversine rather than raising,
            # keeping the delivery pipeline alive when the OSRM demo is
            # unreachable (the whole point of the fallback design).
            last_exc = exc
            if attempt == retries:
                break

    # Fallback: Haversine. Surface the last error in the logs but don't crash.
    # Callers that need to know whether the matrix came from OSRM can re-inspect
    # the value (Haversine matrices are always symmetric and follow the great-circle
    # math). The exception text is logged at WARNING so production log handlers
    # can DLP/redact if needed; we never print to stdout/stderr in production.
    if last_exc is not None:
        _logger.warning(
            "OSRM failed after %d retries, falling back to Haversine: %s",
            retries,
            last_exc,
        )
    return haversine_matrix(coords)
