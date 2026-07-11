"""KivyMD import screen — single-address form + "Add to today's tour".

Threading contract: this screen NEVER calls ``geocoder.geocode`` or
``router.get_distance_matrix`` directly. All slow work goes through
:class:`ui.controllers.optimize_controller.OptimizeController`. The
"Add" button writes the parcel to SQLite (status=pending), then the
controller handles geocoding on a worker thread and the
:class:`MainScreen` reacts to the ``finished`` callback to refresh the
list.
"""
from __future__ import annotations

import logging
from typing import Optional

from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDRaisedButton, MDFlatButton
from kivymd.uix.label import MDLabel
from kivymd.uix.progressbar import MDProgressBar
from kivymd.uix.screen import MDScreen
from kivymd.uix.textfield import MDTextField
from kivy.metrics import dp

from database.db_manager import DBManager

_logger = logging.getLogger("transas.ui.import_screen")


class ImportScreen(MDScreen):
    """Single-address form with a debounced Add button."""

    def __init__(self, db: DBManager, **kwargs):
        super().__init__(**kwargs)
        self.name = "import"
        self._db = db

        root = MDBoxLayout(
            orientation="vertical",
            padding=dp(20),
            spacing=dp(20),
            adaptive_height=True,
        )

        root.add_widget(MDLabel(
            text="Ajouter un colis",
            theme_text_color="Primary",
            font_style="H5",
        ))
        root.add_widget(MDLabel(
            text="Saisissez l'adresse du client,\npuis « Ajouter ».",
            theme_text_color="Secondary",
            font_style="Body2",
        ))

        self._address_field = MDTextField(
            hint_text="Adresse complète (rue, code postal, ville)",
            mode="rectangle",
            multiline=False,
            required=True,
            helper_text_mode="on_focus",
        )
        root.add_widget(self._address_field)

        self._progress = MDProgressBar(
            value=0,
            size_hint_y=None,
            height=dp(6),
        )
        root.add_widget(self._progress)

        self._progress_label = MDLabel(
            text="",
            theme_text_color="Hint",
            font_style="Caption",
        )
        root.add_widget(self._progress_label)

        self._feedback = MDLabel(
            text="",
            theme_text_color="Custom",
            text_color=(0.0, 0.6, 0.0, 1),
            font_style="Body2",
        )
        root.add_widget(self._feedback)

        buttons = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(12),
            adaptive_height=True,
        )
        buttons.add_widget(MDFlatButton(
            text="Voir tournée",
            on_release=lambda _b: self._switch_to_main(),
        ))
        buttons.add_widget(MDRaisedButton(
            text="Ajouter",
            on_release=lambda _b: self._on_add_clicked(),
        ))
        root.add_widget(buttons)

        self.add_widget(root)

    # ------------------------------------------------------------------
    # Public fields (main_screen reads these on lifecycle hooks)
    # ------------------------------------------------------------------

    db: Optional[DBManager] = None  # set in __init__

    # ------------------------------------------------------------------
    # Internal handlers
    # ------------------------------------------------------------------

    def _on_add_clicked(self) -> None:
        address = (self._address_field.text or "").strip()
        if not address:
            self._set_feedback("Adresse requise.", error=True)
            return
        try:
            new_id = self._db.add_parcel(address)
        except (ValueError, TypeError) as exc:
            self._set_feedback(f"Refusé : {exc}", error=True)
            return
        self._set_feedback(
            f"Colis #{new_id} ajouté. Géocodage lancé en arrière-plan.",
            error=False,
        )
        self._address_field.text = ""
        self._progress_label.text = "Géocodage différé (à l'optimisation)…"
        _logger.info("Imported parcel #%d", new_id)

    def _set_feedback(self, message: str, *, error: bool) -> None:
        self._feedback.text = message
        self._feedback.text_color = (
            (0.85, 0.2, 0.2, 1) if error else (0.0, 0.6, 0.0, 1),
        )

    def _switch_to_main(self) -> None:
        if self.manager:
            self.manager.current = "main"
