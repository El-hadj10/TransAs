"""Unit tests for ``core.router``."""
from unittest.mock import patch, MagicMock

import pytest

from core import router


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_rate_limit(monkeypatch):
    """No-op placeholder hook so we can stub remote later without state leaks."""
    yield


def _mock_osrm_response(distances, code="Ok"):
    fake = MagicMock()
    fake.json.return_value = {"code": code, "distances": distances}
    fake.raise_for_status = MagicMock()
    return fake


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_coordinates_to_path_format():
    path = router.coordinates_to_path([(48.8566, 2.3522), (48.8606, 2.3376)])
    assert path == "2.3522,48.8566;2.3376,48.8606"


def test_get_distance_matrix_returns_matrix_from_osrm():
    coords = [(48.8566, 2.3522), (48.8606, 2.3376), (48.8738, 2.2950)]
    distances = [[0, 1500, 4500], [1500, 0, 3500], [4500, 3500, 0]]
    response = _mock_osrm_response(distances)

    with patch("core.router.requests.get", return_value=response) as mock_get:
        matrix = router.get_distance_matrix(coords)

    assert matrix == distances
    assert mock_get.call_count == 1


def test_get_distance_matrix_single_coord():
    assert router.get_distance_matrix([(48.85, 2.35)]) == [[0.0]]


def test_get_distance_matrix_empty_coords():
    assert router.get_distance_matrix([]) == []


def test_get_distance_matrix_falls_back_to_haversine_on_failure():
    coords = [(48.8566, 2.3522), (48.8606, 2.3376)]
    with patch("core.router.requests.get",
               side_effect=ConnectionError("network down")):
        matrix = router.get_distance_matrix(coords, retries=1)
    # Paris center -> Paris west ≈ 1500 m haversine
    assert 1000 < matrix[0][1] < 2500


def test_get_distance_matrix_retries_then_succeeds():
    coords = [(48.8566, 2.3522), (48.8738, 2.2950)]
    distances = [[0, 5300], [5300, 0]]
    bad = MagicMock(side_effect=ConnectionError("flaky"))
    good = _mock_osrm_response(distances)

    with patch("core.router.requests.get", side_effect=[bad, good]) as mock_get:
        matrix = router.get_distance_matrix(coords, retries=2)
    assert matrix == distances
    assert mock_get.call_count == 2


def test_get_distance_matrix_osrm_non_ok_code_falls_back():
    coords = [(48.8566, 2.3522), (48.8738, 2.2950)]
    bad_code = _mock_osrm_response(None, code="NoRoute")

    with patch("core.router.requests.get", return_value=bad_code):
        matrix = router.get_distance_matrix(coords, retries=1)
    # Haversine fallback should yield a sensible value.
    assert 1000 < matrix[0][1] < 10_000


def test_haversine_distance_paris_to_lyon():
    # Paris (48.8566, 2.3522) -> Lyon (45.7640, 4.8357) ≈ 392 km
    d = router.haversine_distance(48.8566, 2.3522, 45.7640, 4.8357)
    assert 370_000 < d < 410_000


def test_haversine_distance_same_point_is_zero():
    assert router.haversine_distance(48.85, 2.35, 48.85, 2.35) == 0.0


def test_haversine_matrix_is_symmetric():
    coords = [(48.85, 2.35), (48.86, 2.34), (45.76, 4.83)]
    m = router.haversine_matrix(coords)
    n = len(coords)
    for i in range(n):
        for j in range(n):
            assert m[i][j] == pytest.approx(m[j][i], rel=1e-9)
        assert m[i][i] == 0.0
