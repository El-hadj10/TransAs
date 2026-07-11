"""Data models for the persistence layer.

These dataclasses are intentionally render-friendly: they sit between
the SQLite rows (managed by ``db_manager``) and the UI layer (Step 3),
and they carry just enough information to round-trip through the
optimiser (``core.optimizer.optimize``), which expects each stop to
expose ``lat`` and ``lon`` (and optionally ``id``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional, Tuple


@dataclass
class Parcel:
    """A single delivery destination.

    Attributes:
        id: SQLite primary key. ``None`` until committed by
            ``DBManager.add_parcel``.
        address: Free-form postal string, exactly what the user typed.
        lat, lon: GPS coordinates (set after geocoding).
        status: ``"pending"`` (default) or ``"delivered"``.
        created_at: ISO-8601 UTC timestamp; auto-stamped at insert time.
    """

    address: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    status: str = "pending"
    id: Optional[int] = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )

    @property
    def coords(self) -> Optional[Tuple[float, float]]:
        """Return ``(lat, lon)`` when both are set, else ``None``."""
        if self.lat is None or self.lon is None:
            return None
        return (self.lat, self.lon)

    def to_stop(self) -> dict:
        """Project to the dict shape that ``core.optimizer`` accepts."""
        return {"id": self.id, "lat": self.lat, "lon": self.lon}


@dataclass
class Tour:
    """An ordered sequence of parcel IDs for a given day.

    Attributes:
        id: SQLite primary key (``None`` until committed).
        date: ISO date string ``YYYY-MM-DD``.
        ordered_indices: Parcel IDs in delivery order. Round-trips
            through JSON in the SQLite ``tours`` table.
    """

    date: str
    ordered_indices: list
    id: Optional[int] = None

    @classmethod
    def for_today(cls, parcel_ids: list) -> "Tour":
        return cls(
            id=None,
            date=date.today().isoformat(),
            ordered_indices=list(parcel_ids),
        )
