"""Unit tests for the SQLite persistence layer (Step 2).

Each test points ``DBManager`` at a fresh file under ``tmp_path``,
so tests are isolated and the real database never gets touched.
"""
from datetime import date

import pytest

from database.db_manager import DBManager


@pytest.fixture
def db(tmp_path):
    db_file = tmp_path / "transas_test.db"
    instance = DBManager(db_path=str(db_file))
    yield instance
    # Connections are closed by the context manager; tmp_path auto-cleans.


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def test_db_creates_schema_on_init(db):
    with db._connect_ctx() as conn:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()}
    assert {"parcels", "tours"}.issubset(names)


def test_db_indexes_are_created(db):
    with db._connect_ctx() as conn:
        info = list(conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall())
    names = {row["name"] for row in info if row["name"]}
    assert {"idx_parcels_status", "idx_tours_date"} <= names


# ---------------------------------------------------------------------------
# Parcels — CRUD
# ---------------------------------------------------------------------------

def test_add_parcel_returns_incrementing_ids(db):
    p1 = db.add_parcel("10 rue de Rivoli, Paris")
    p2 = db.add_parcel("5 avenue Hugo, Lyon")
    p3 = db.add_parcel("Place Bellecour, Lyon")
    assert (p1, p2, p3) == (1, 2, 3)


def test_update_parcel_coords(db):
    pid = db.add_parcel("Beaubourg, Paris")
    db.update_parcel_coords(pid, 48.8606, 2.3522)
    parcel = db.get_parcel(pid)
    assert parcel is not None
    assert parcel.lat == pytest.approx(48.8606)
    assert parcel.lon == pytest.approx(2.3522)


def test_get_parcel_returns_none_for_unknown_id(db):
    assert db.get_parcel(99999) is None


def test_list_pending_filters_only_pending(db):
    db.add_parcel("A")
    db.add_parcel("B")
    db.add_parcel("C")
    pending = db.list_pending()
    assert len(pending) == 3
    assert {p.address for p in pending} == {"A", "B", "C"}

    db.mark_delivered(pending[0].id)
    pending = db.list_pending()
    assert {p.address for p in pending} == {"B", "C"}

    db.mark_delivered(pending[0].id)
    db.mark_delivered(pending[1].id)
    assert db.list_pending() == []


def test_mark_delivered_changes_status_and_is_idempotent(db):
    pid = db.add_parcel("Test")
    db.mark_delivered(pid)
    db.mark_delivered(pid)  # idempotent
    parcel = db.get_parcel(pid)
    assert parcel.status == "delivered"


def test_delete_parcel_removes_row(db):
    pid = db.add_parcel("Throwaway")
    db.delete_parcel(pid)
    assert db.get_parcel(pid) is None


# ---------------------------------------------------------------------------
# Tours
# ---------------------------------------------------------------------------

def test_save_and_load_tour_round_trip(db):
    tour_id = db.save_tour("2026-07-10", [3, 1, 4, 2, 5])
    loaded = db.load_tour_for_date("2026-07-10")
    assert loaded is not None
    assert loaded.id == tour_id
    assert loaded.date == "2026-07-10"
    assert loaded.ordered_indices == [3, 1, 4, 2, 5]


def test_load_tour_for_date_returns_latest_when_multiple(db):
    db.save_tour("2026-07-10", [1, 2, 3])
    db.save_tour("2026-07-10", [4, 5, 6, 7])
    loaded = db.load_tour_for_date("2026-07-10")
    assert loaded.ordered_indices == [4, 5, 6, 7]


def test_load_tour_for_date_returns_none_when_absent(db):
    assert db.load_tour_for_date("1990-01-01") is None


def test_load_tour_for_date_raises_value_error_on_corrupt_indices(db):
    """If ``ordered_indices`` is corrupted in storage (e.g. legacy data
    containing strings instead of ints), ``load_tour_for_date`` must raise
    ``ValueError`` rather than letting the optimiser crash later on
    ``matrix[i][j]`` with a confusing TypeError."""
    with db._connect_ctx() as conn:
        conn.execute(
            "INSERT INTO tours (date, ordered_indices) VALUES (?, ?)",
            ("2026-07-10", '["abc", "def"]'),
        )
    with pytest.raises(ValueError, match=r"list\[int\]"):
        db.load_tour_for_date("2026-07-10")


def test_load_tour_for_date_raises_on_non_list_payload(db):
    """If ``ordered_indices`` is not a JSON list at all (legacy object/dict),
    the same ValueError path must fire."""
    with db._connect_ctx() as conn:
        conn.execute(
            "INSERT INTO tours (date, ordered_indices) VALUES (?, ?)",
            ("2026-07-10", '{"foo": 1}'),
        )
    with pytest.raises(ValueError):
        db.load_tour_for_date("2026-07-10")


def test_load_today_tour_returns_today(db):
    today = date.today().isoformat()
    db.save_tour(today, [10, 20, 30])
    loaded = db.load_today_tour()
    assert loaded is not None
    assert loaded.date == today
    assert loaded.ordered_indices == [10, 20, 30]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

def test_parcel_coords_property():
    from database.models import Parcel
    p = Parcel(address="x")
    assert p.coords is None
    p.lat, p.lon = 48.85, 2.35
    assert p.coords == (48.85, 2.35)


def test_parcel_to_stop_shape():
    from database.models import Parcel
    p = Parcel(address="x", id=7, lat=48.85, lon=2.35)
    assert p.to_stop() == {"id": 7, "lat": 48.85, "lon": 2.35}


def test_tour_for_today_uses_local_date():
    from database.models import Tour
    t = Tour.for_today([1, 2, 3])
    assert t.date == date.today().isoformat()
    assert t.ordered_indices == [1, 2, 3]
    assert t.id is None
