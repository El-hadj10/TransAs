"""Unit tests for ``core.geocoder``.

All tests:
  * patch ``config.Config.CACHE_DIR`` to a ``tmp_path`` so the real cache
    is never touched;
  * patch ``core.geocoder.time.sleep`` to a no-op so the rate-limiter
    never blocks a test for 1.1 s;
  * reset and pin the module-level rate-limit clock;
  * mock ``requests.get`` to avoid any network access.
"""
from unittest.mock import patch, MagicMock

import pytest

import config
from core import geocoder


# ---------------------------------------------------------------------------
# Fixture: redirect cache to tmp_path, kill the rate-limit sleep, pin the clock
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def redirect_cache_and_disable_sleep(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(config.Config, "GEOCODING_CACHE_FILE", "geocoding_cache.json")
    # Kill the rate-limit sleep — tests don't tolerate real wall-clock pacing.
    monkeypatch.setattr(geocoder.time, "sleep", lambda seconds: None)
    # Pin the rate-limit clock far enough in the past to skip the elapsed check
    # for the first call (and reset it between calls inside tests that need to).
    monkeypatch.setattr(geocoder, "_last_request_ts", 0.0)


def _mock_nominatim_response(payload):
    fake = MagicMock()
    fake.json.return_value = payload
    fake.raise_for_status = MagicMock()
    return fake


def _set_monotonic_to_now():
    """Reset ``_last_request_ts`` to ``monotonic()`` so future elapsed checks pass."""
    import time as _t
    geocoder._last_request_ts = _t.monotonic()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_geocode_cache_miss_then_hit():
    """First call hits the network (mocked), second call hits the cache."""
    _set_monotonic_to_now()
    response = _mock_nominatim_response([{
        "lat": "48.8566", "lon": "2.3522", "display_name": "Paris, France"
    }])
    with patch("core.geocoder.requests.get", return_value=response) as mock_get:
        first = geocoder.geocode("Paris, France")
        second = geocoder.geocode("Paris, France")  # cache hit — no network call
    assert mock_get.call_count == 1
    assert first.source == "nominatim"
    assert second.source == "cache"
    assert (first.lat, first.lon) == (second.lat, second.lon)


def test_geocode_returns_none_when_nominatim_empty():
    _set_monotonic_to_now()
    response = _mock_nominatim_response([])
    with patch("core.geocoder.requests.get", return_value=response):
        result = geocoder.geocode("asdfghjkl-no-such-place")
    assert result is None


def test_geocode_is_case_insensitive():
    _set_monotonic_to_now()
    response = _mock_nominatim_response([{
        "lat": "48.8566", "lon": "2.3522", "display_name": "Paris, France"
    }])
    with patch("core.geocoder.requests.get", return_value=response) as mock_get:
        geocoder.geocode("Paris")
        geocoder.geocode("PARIS")
        geocoder.geocode("paris")
    assert mock_get.call_count == 1


def test_geocode_use_cache_false_skips_cache():
    """With use_cache=False, every call must hit the network."""
    _set_monotonic_to_now()
    response = _mock_nominatim_response([{
        "lat": "48.8566", "lon": "2.3522", "display_name": "Paris, France"
    }])
    with patch("core.geocoder.requests.get", return_value=response) as mock_get:
        geocoder.geocode("Paris", use_cache=False)
        _set_monotonic_to_now()  # pretend 1.1 s passed so the next call doesn't sleep
        geocoder.geocode("Paris", use_cache=False)
    assert mock_get.call_count == 2


def test_geocode_empty_address_returns_none():
    _set_monotonic_to_now()
    assert geocoder.geocode("") is None
    assert geocoder.geocode("   ") is None


def test_clear_cache_removes_file(tmp_path):
    _set_monotonic_to_now()
    response = _mock_nominatim_response([{
        "lat": "48.8566", "lon": "2.3522", "display_name": "Paris, France"
    }])
    with patch("core.geocoder.requests.get", return_value=response):
        geocoder.geocode("Paris, France")
    cache_file = tmp_path / "geocoding_cache.json"
    assert cache_file.exists()
    geocoder.clear_cache()
    assert not cache_file.exists()


def test_geocode_thread_safe_under_lock(monkeypatch):
    """Two concurrent ``geocode`` calls cannot both be inside the
    rate-limit critical section at the same time.

    The lock lives around ``requests.get``; we therefore count how many
    mock responses are in-flight at once. With the lock, the maximum is 1.
    Without the lock, it can go to 2.
    """
    import threading
    import time as real_time

    # The autouse fixture already mocks time.sleep and pins _last_request_ts,
    # so we don't need to repeat it here. But we ensure both threads see a
    # rate-limit-elapsed clock that forces them through the lock path.
    monkeypatch.setattr(geocoder, "_last_request_ts", real_time.monotonic() - 100.0)

    in_flight: list = []
    max_in_flight = [0]
    state_lock = threading.Lock()

    def slow_response(*args, **kwargs):
        with state_lock:
            in_flight.append(True)
            max_in_flight[0] = max(max_in_flight[0], len(in_flight))
        real_time.sleep(0.05)  # simulate real network round-trip
        with state_lock:
            in_flight.pop()
        fake = MagicMock()
        fake.json.return_value = [{
            "lat": "48.85", "lon": "2.35", "display_name": "Paris"
        }]
        fake.raise_for_status = MagicMock()
        return fake

    def thread_target(_):
        with patch("core.geocoder.requests.get", side_effect=slow_response):
            geocoder.geocode("An address")

    t1 = threading.Thread(target=thread_target, args=("A",))
    t2 = threading.Thread(target=thread_target, args=("B",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert max_in_flight[0] == 1, (
        f"rate-limit lock did not serialise: observed max-in-flight = "
        f"{max_in_flight[0]} (expected 1)"
    )
