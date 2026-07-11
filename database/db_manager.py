"""SQLite-backed CRUD layer for parcels and tours.

Wraps a single SQLite database file with a row-factory connection and
a context-manager that commits on success and closes on exit. The
schema is created lazily on first instantiation, so the UI layer can
construct a ``DBManager`` ad-hoc without worrying about migrations.

Schema (MVP — see ``knowledge.md`` and ``structure.md`` Step 2):

    parcels(id PK, address, lat, lon, status, created_at)
    tours(id PK, date, ordered_indices JSON, created_at)

Indexes on ``parcels(status)`` and ``tours(date)`` keep the two
hottest queries (``list_pending`` / ``load_today_tour``) cheap.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator, List, Optional

import config

from .models import Parcel, Tour


class DBManager:
    """Thin SQLite wrapper with first-class Parcel/Tour CRUD.

    The connection is short-lived per call (through ``_connect_ctx``)
    so SQLite's locking discipline handles concurrent reads/writes from
    a Kivy UI thread without surprises.
    """

    # Single source of truth for the schema. Any future DDL addition goes
    # here as a new tuple entry; ``_init_schema`` runs the whole list
    # inside one ``BEGIN IMMEDIATE``/``COMMIT`` so the migration stays
    # atomic by construction. This replaces the in-code ``COMMIT`` boundary
    # comment that was fragile in earlier iterations.
    _SCHEMA: tuple = (
        """CREATE TABLE IF NOT EXISTS parcels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            address TEXT NOT NULL,
            lat REAL,
            lon REAL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS tours (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            ordered_indices TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS idx_parcels_status ON parcels(status)",
        "CREATE INDEX IF NOT EXISTS idx_tours_date    ON tours(date)",
    )

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path if db_path is not None else str(
            Path(config.Config.PROJECT_ROOT) / "transas.db"
        )
        self._init_schema()

    # ------------------------------------------------------------------
    # Input validation (DoS hardening)
    # ------------------------------------------------------------------

    # Maximum length of an ``address`` field. Postal addresses are typically
    # well under 200 chars; we cap conservatively at 256 to bound memory
    # growth and reject pathological inputs from a corrupted UI.
    _MAX_ADDRESS_LEN: int = 256

    # Latitude/longitude ranges accepted by SQLite. Anything outside is
    # rejected before INSERT so a malformed geocoder response cannot
    # corrupt the database with sentinel values like ``lat=1e30``.
    _LAT_RANGE: tuple = (-90.0, 90.0)
    _LON_RANGE: tuple = (-180.0, 180.0)

    @staticmethod
    def _validate_address(address: str) -> str:
        if not isinstance(address, str):
            raise TypeError(f"address must be str, got {type(address).__name__}")
        if not address.strip():
            raise ValueError("address must not be empty or whitespace-only")
        if len(address) > DBManager._MAX_ADDRESS_LEN:
            raise ValueError(
                f"address exceeds {DBManager._MAX_ADDRESS_LEN} chars "
                f"(got {len(address)}) \u2014 reject to bound memory growth"
            )
        return address

    @staticmethod
    def _validate_coords(lat: Optional[float], lon: Optional[float]) -> None:
        # Validate each non-None coord independently. Returning early on
        # "either is None" would silently let ``update_parcel_coords(
        # parcel_id, lat=1e30, lon=None)`` slip a sentinel value into the
        # database even though lat is infinite. Real-world geocoder feeds
        # always set both together, but the contract should match the doc.
        for value, bounds, name in (
            (lat, DBManager._LAT_RANGE, "lat"),
            (lon, DBManager._LON_RANGE, "lon"),
        ):
            if value is None:
                continue
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError(f"{name}={value!r} is not numeric")
            lo, hi = bounds
            if not (lo <= float(value) <= hi):
                raise ValueError(f"{name} {value!r} outside [{lo}, {hi}]")

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def _connect_ctx(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        # We bypass ``_connect_ctx`` and manage the connection lifecycle
        # inline for two reasons:
        #
        # 1. Python sqlite3 in legacy autocommit (the default until Python
        #    3.12) makes ``executescript`` emit an implicit COMMIT before
        #    running its script — which breaks any surrounding explicit
        #    transaction. To keep DDL atomic we therefore call each
        #    statement via ``conn.execute(...)`` iterating ``self._SCHEMA``.
        #
        # 2. ``_connect_ctx`` issues an implicit ``conn.commit()`` on
        #    successful exit. After our explicit COMMIT, that call would
        #    hit "cannot commit - no transaction is active" on legacy
        #    autocommit builds.
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for ddl in self._SCHEMA:
                    conn.execute(ddl)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Parcels — CRUD
    # ------------------------------------------------------------------

    def add_parcel(self, address: str,
                   lat: Optional[float] = None,
                   lon: Optional[float] = None) -> int:
        """Insert a parcel, return the assigned id.

        Both ``address`` and the optional coordinates are validated before
        INSERT. The address is rejected when empty, non-string, or longer
        than ``_MAX_ADDRESS_LEN`` (256 chars). Coord-values are bounded to
        the latitude/longitude ranges so a faulty geocoder response cannot
        poison the database (defense-in-depth against SQL injection or
        future-validator regressions).
        """
        address = self._validate_address(address)
        self._validate_coords(lat, lon)
        with self._connect_ctx() as conn:
            cur = conn.execute(
                "INSERT INTO parcels (address, lat, lon) VALUES (?, ?, ?)",
                (address, lat, lon),
            )
            return cur.lastrowid

    def update_parcel_coords(self, parcel_id: int,
                             lat: float, lon: float) -> None:
        """Backfill GPS coordinates after geocoding.

        Range-checks the new lat/lon before UPDATE so a corrupted geocoder
        response cannot inject sentinel values into the database.
        """
        self._validate_coords(lat, lon)
        with self._connect_ctx() as conn:
            conn.execute(
                "UPDATE parcels SET lat = ?, lon = ? WHERE id = ?",
                (lat, lon, parcel_id),
            )

    def get_parcel(self, parcel_id: int) -> Optional[Parcel]:
        with self._connect_ctx() as conn:
            row = conn.execute(
                "SELECT id, address, lat, lon, status, created_at "
                "FROM parcels WHERE id = ?",
                (parcel_id,),
            ).fetchone()
        return self._row_to_parcel(row) if row else None

    def list_pending(self) -> List[Parcel]:
        """Return parcels in ``pending`` status, oldest first.

        The status string is sourced from ``config.Config.STATUS_PENDING``
        so ``mark_delivered`` and ``list_pending`` always agree on the
        vocabulary (no second source of truth).
        """
        return self._fetch_by_status(config.Config.STATUS_PENDING)

    def list_all(self) -> List[Parcel]:
        """Return every parcel, oldest first (debug / export)."""
        with self._connect_ctx() as conn:
            rows = conn.execute(
                "SELECT id, address, lat, lon, status, created_at "
                "FROM parcels ORDER BY created_at ASC, id ASC"
            ).fetchall()
        return [self._row_to_parcel(r) for r in rows]

    def mark_delivered(self, parcel_id: int) -> None:
        """Transition ``pending`` → ``delivered``. Idempotent."""
        with self._connect_ctx() as conn:
            conn.execute(
                "UPDATE parcels SET status = ? WHERE id = ?",
                (config.Config.STATUS_DELIVERED, parcel_id),
            )

    def delete_parcel(self, parcel_id: int) -> None:
        with self._connect_ctx() as conn:
            conn.execute("DELETE FROM parcels WHERE id = ?", (parcel_id,))

    # ------------------------------------------------------------------
    # Tours — ordered route persistence
    # ------------------------------------------------------------------

    def save_tour(self, date_str: str, ordered_indices: List[int]) -> int:
        """Persist an ordered route for a given day, return tour id."""
        with self._connect_ctx() as conn:
            cur = conn.execute(
                "INSERT INTO tours (date, ordered_indices) VALUES (?, ?)",
                (date_str, json.dumps(list(ordered_indices))),
            )
            return cur.lastrowid

    def load_today_tour(self) -> Optional[Tour]:
        """Return the most recent tour for today, or ``None``."""
        return self.load_tour_for_date(date.today().isoformat())

    def load_tour_for_date(self, target_date: str) -> Optional[Tour]:
        """Return the most recent tour for ``target_date``, or ``None``.

        The ``ordered_indices`` JSON column is decoded and validated as a
        list of integers — the optimiser contract. Any other shape (a list of
        strings from a future migration, or a dict) raises ``ValueError``
        so the corruption does not surface deep inside the routing hot path.
        """
        with self._connect_ctx() as conn:
            row = conn.execute(
                "SELECT id, date, ordered_indices FROM tours "
                "WHERE date = ? ORDER BY created_at DESC, id DESC LIMIT 1",
                (target_date,),
            ).fetchone()
        if not row:
            return None
        raw = json.loads(row["ordered_indices"])
        if not isinstance(raw, list) or not all(isinstance(x, int) for x in raw):
            raise ValueError(
                f"Tour {row['id']} on {row['date']} stored ordered_indices "
                f"as {type(raw).__name__}, expected list[int]"
            )
        return Tour(id=row["id"], date=row["date"], ordered_indices=raw)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_by_status(self, status: str) -> List[Parcel]:
        with self._connect_ctx() as conn:
            rows = conn.execute(
                "SELECT id, address, lat, lon, status, created_at "
                "FROM parcels WHERE status = ? ORDER BY created_at ASC, id ASC",
                (status,),
            ).fetchall()
        return [self._row_to_parcel(r) for r in rows]

    @staticmethod
    def _row_to_parcel(row: sqlite3.Row) -> Parcel:
        return Parcel(
            id=row["id"],
            address=row["address"],
            lat=row["lat"],
            lon=row["lon"],
            status=row["status"],
            created_at=row["created_at"],
        )
