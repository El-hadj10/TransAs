"""MDCard row for a single parcel — reusable across screens.

Encapsulates the visual contract for one stop in the optimised tour:
a heading (N° + ETA), a body (address + lat/lon) and an action row
(delivered button + status badge, optionally Navigation).
"""
from __future__ import annotations

from typing import Callable, Optional, Tuple

from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDRaisedButton
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivy.metrics import dp


STATUS_COLORS = {
    "pending":   (1.0, 0.55, 0.0, 1),    # TransAs orange
    "delivered": (0.0, 0.7, 0.3, 1),     # success green
}


def build_parcel_card(
    *,
    order: int,
    address: str,
    coord_text: str,
    eta_text: str,
    status: str,
    on_delivered: Optional[Callable[[int], None]] = None,
    parcel_id: Optional[int] = None,
    on_navigate: Optional[Callable[[float, float, str], None]] = None,
    navigate_label: Optional[Tuple[float, float, str]] = None,
    show_deliver_button: bool = True,
) -> MDCard:
    """Build a single parcel row as an :class:`MDCard`.

    Args:
        order: 1-indexed delivery order within the today's tour.
        address: Free-form postal address (truncated visually if too long).
        coord_text: "" or "lat,lon" rounded string for the body line.
        eta_text: "ETA 12:30" or "" for un-geocoded pending parcels.
        status: "pending" or "delivered" (controls badge color).
        on_delivered: callback receiving the ``parcel_id`` when the user
                      taps "Livré".
        on_navigate: callback receiving ``(lat, lon, label)`` when the
                     driver taps "Naviguer". Used only on the first
                     stop of the tour (see ``navigate_label``).
        navigate_label: Optional ``(lat, lon, label)`` tuple; if set,
                        the "Naviguer" button is rendered alongside
                        "Livré" in the actions row.
        parcel_id: Required if ``on_delivered`` is set.
        show_deliver_button: False on the map screen (read-only context).
    """
    # Auto-grow the card so an extra action button never overflows.
    has_nav = navigate_label is not None and on_navigate is not None
    card_height = dp(124) if has_nav else dp(96)

    card = MDCard(
        orientation="vertical",
        padding=dp(12),
        spacing=dp(4),
        size_hint_y=None,
        height=card_height,
        radius=[dp(12)],
        elevation=2,
    )

    # ── Heading row: order badge + ETA + status pill ────────────────
    heading = MDBoxLayout(
        orientation="horizontal",
        spacing=dp(8),
        adaptive_height=True,
    )
    heading.add_widget(MDLabel(
        text=f"#{order}",
        theme_text_color="Primary",
        font_style="H6",
        size_hint_x=None,
        width=dp(48),
    ))
    heading.add_widget(MDLabel(
        text=eta_text,
        theme_text_color="Secondary",
        font_style="Body2",
    ))
    heading.add_widget(MDLabel(
        text=_status_label(status),
        theme_text_color="Custom",
        text_color=STATUS_COLORS.get(status, (0.5, 0.5, 0.5, 1)),
        font_style="Caption",
        size_hint_x=None,
        width=dp(96),
        halign="right",
    ))

    # ── Body row: address ──────────────────────────────────────────
    body = MDLabel(
        text=address,
        theme_text_color="Primary",
        font_style="Body1",
        shorten=True,
        shorten_from="right",
    )

    card.add_widget(heading)
    card.add_widget(body)

    # ── Action row (deliver + optional navigation) ────────────────
    action_widgets = []
    if show_deliver_button and on_delivered is not None and parcel_id is not None:
        action_widgets.append(MDRaisedButton(
            text="Livré" if status == "pending" else "Annuler",
            md_bg_color=STATUS_COLORS.get(status, (0.5, 0.5, 0.5, 1)),
            text_color=(1, 1, 1, 1),
            size_hint_x=None,
            width=dp(120),
            on_release=lambda _btn: on_delivered(parcel_id),
            disabled=(status == "delivered"),
        ))

    if has_nav:
        lat, lon, label = navigate_label   # type: ignore[misc]
        action_widgets.append(MDRaisedButton(
            text="Naviguer",
            md_bg_color=(0.1, 0.4, 0.85, 1),
            text_color=(1, 1, 1, 1),
            size_hint_x=None,
            width=dp(120),
            on_release=lambda _btn, lat=lat, lon=lon, label=label:
                on_navigate(lat, lon, label),
        ))

    if action_widgets:
        actions = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(8),
            adaptive_height=True,
        )
        if coord_text:
            actions.add_widget(MDLabel(
                text=coord_text,
                theme_text_color="Hint",
                font_style="Caption",
            ))
        for w in action_widgets:
            actions.add_widget(w)
        card.add_widget(actions)
    elif coord_text:
        card.add_widget(MDLabel(
            text=coord_text,
            theme_text_color="Hint",
            font_style="Caption",
        ))
    return card


def _status_label(status: str) -> str:
    return {"pending": "À livrer", "delivered": "Livré"}.get(status, status)
