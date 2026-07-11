"""Top-of-route summary header (stops/km/ETA + optimisation mode badge)."""
from __future__ import annotations

from typing import Optional

from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivy.metrics import dp


def build_route_overview(
    *,
    stops_count: int,
    total_km: Optional[float],
    started_at_label: str = "",
    mode: str = "OSRM",
) -> MDBoxLayout:
    """Build a one-line summary header for the today's tour.

    Args:
        stops_count: Number of stops (≥ 0).
        total_km: Total road distance if known (else ``None`` to dash-display).
        started_at_label: e.g. "Démarré à 08:45" — UI label only.
        mode: "OSRM" or "Haversine" — small badge so the driver knows
              whether the route is road-accurate or straight-line fallback.
    """
    distance_text = (
        f"{total_km:.1f} km" if total_km is not None else "— km"
    )
    badges_row = MDBoxLayout(
        orientation="horizontal",
        spacing=dp(12),
        adaptive_height=True,
        padding=(dp(8), dp(8), dp(8), dp(4)),
    )
    badges_row.add_widget(MDLabel(
        text=f"{stops_count} stops",
        theme_text_color="Primary",
        font_style="Subtitle1",
    ))
    badges_row.add_widget(MDLabel(
        text=distance_text,
        theme_text_color="Primary",
        font_style="Subtitle1",
    ))
    badges_row.add_widget(MDLabel(
        text=mode,
        theme_text_color="Custom",
        text_color=(1.0, 0.55, 0.0, 1)
        if mode == "OSRM" else (0.4, 0.4, 0.4, 1),
        font_style="Caption",
        size_hint_x=None,
        width=dp(96),
        halign="right",
    ))

    if started_at_label:
        badges_row.add_widget(MDLabel(
            text=started_at_label,
            theme_text_color="Hint",
            font_style="Caption",
        ))
    return badges_row
