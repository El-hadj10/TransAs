"""Android speech-to-text bridge for address entry."""
from __future__ import annotations

import logging

_logger = logging.getLogger("transas.ui.speech")

REQUEST_CODE = 95350


def _main_thread(fn, *args) -> None:
    """Run ``fn`` on Kivy's main thread.

    ``android.activity`` delivers ``on_activity_result`` from the Android UI
    thread; touching Kivy widgets or the SQLite connection there can fail
    silently, so every callback is handed to the clock.
    """
    try:
        from kivy.clock import Clock
        Clock.schedule_once(lambda _dt: fn(*args), 0)
    except Exception:  # no Kivy clock (tests, early import)
        fn(*args)


def request_address(callback, error_callback) -> bool:
    """Open Android's speech recognizer and return the best transcript."""
    try:
        from kivy.utils import platform
        if platform != "android":
            return False
        from android import activity  # type: ignore[import-not-found]
        from jnius import autoclass  # type: ignore[import-not-found]
        Intent = autoclass("android.content.Intent")
        RecognizerIntent = autoclass("android.speech.RecognizerIntent")
        Activity = autoclass("android.app.Activity")

        def on_result(request_code, result_code, intent):
            if request_code != REQUEST_CODE:
                return
            activity.unbind(on_activity_result=on_result)
            _logger.info(
                "voice: activity result code=%s ok=%s intent=%s",
                result_code, result_code == Activity.RESULT_OK, intent,
            )
            if result_code != Activity.RESULT_OK or intent is None:
                _main_thread(error_callback, "Aucune adresse dictée.")
                return
            results = None
            try:
                results = intent.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)
            except Exception as exc:
                _logger.warning("voice: getStringArrayListExtra failed: %s", exc)
            if results is None:
                try:
                    extras = intent.getExtras()
                    results = extras.getCharSequenceArrayList(RecognizerIntent.EXTRA_RESULTS) if extras else None
                except Exception as exc:
                    _logger.warning("voice: extras fallback failed: %s", exc)
            if results is None or results.size() == 0:
                _logger.warning("voice: no transcript in result extras")
                _main_thread(error_callback, "Aucune adresse reconnue.")
                return
            text = str(results.get(0)).strip()
            _logger.info("voice: transcript=%r", text)
            if not text:
                _main_thread(error_callback, "Aucune adresse reconnue.")
                return
            _main_thread(callback, text)

        # ``android.activity`` only exposes ``bind``/``unbind`` in this p4a
        # build — it has no ``startActivityForResult`` helper. The Java-side
        # entry point is a method on the running PythonActivity.
        PythonActivity = autoclass("org.kivy.android.PythonActivity")

        activity.bind(on_activity_result=on_result)
        intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "fr-FR")
        intent.putExtra(RecognizerIntent.EXTRA_PROMPT, "Dictez une adresse complète")
        PythonActivity.mActivity.startActivityForResult(intent, REQUEST_CODE)
        _logger.info("voice: recognizer started (request=%s)", REQUEST_CODE)
        return True
    except Exception as exc:
        _logger.exception("voice: recognizer unavailable")
        _main_thread(error_callback, f"Saisie vocale indisponible : {exc}")
        return False
