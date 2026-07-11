"""Pure utility helpers for URI handling — NO Kivy imports.

Why this lives outside :mod:`ui.screens.main_screen`: importing the
main screen for a one-line helper pulls in ``kivy.uix.*`` / ``kivyMD.*``,
which crashes the import phase on a display-less runner (CI / sandbox /
pytest). Keeping the helpers here keeps the test surface narrow and
allows reuse on any platform.
"""
from __future__ import annotations

from typing import Tuple
from urllib.parse import quote


_SAFE_FOR_LABEL = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
                      "0123456789-_. ")


def sanitize_label(label: str) -> str:
    """Strip non-URI-safe characters from a geo: label.

    Rules:
      * Spaces, commas, apostrophes, newlines, hashes, bangs and any
        other non-alphanumeric ASCII chars → mapped to single spaces.
      * Length is capped at 60 chars to stay inside typical Android
        intent extras limits.
      * Output is stripped of leading/trailing whitespace.
    """
    cleaned = "".join(c if c in _SAFE_FOR_LABEL else " " for c in label)
    return cleaned.strip()[:60]


def build_geo_uri(lat: float, lon: float, label: str = "") -> str:
    """Build an Android ``geo:lat,lon?q=lat,lon(label)`` URI.

    The label is URL-encoded (spaces → ``%20``) so the receiving intent
    parser doesn't truncate the label at the first space.
    """
    base = f"geo:{lat},{lon}"
    if label:
        safe = sanitize_label(label)
        if safe:
            base += f"?q={lat},{lon}({quote(safe, safe='')})"
    return base


def build_google_maps_web_url(lat: float, lon: float) -> str:
    """Desktop fallback URL (opens Google Maps in any web browser)."""
    return f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"


def coords_label(lat: float, lon: float, *, precision: int = 4) -> str:
    """Format a compact coordinate label like ``48.8530, 2.3500``."""
    return f"{lat:.{precision}f}, {lon:.{precision}f}"
