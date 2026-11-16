"""Android speech-to-text bridge for address entry."""
from __future__ import annotations


REQUEST_CODE = 95350


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
            if result_code != Activity.RESULT_OK or intent is None:
                error_callback("Aucune adresse dictée.")
                return
            results = intent.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)
            if results is None or results.size() == 0:
                error_callback("Aucune adresse reconnue.")
                return
            callback(str(results.get(0)))

        activity.bind(on_activity_result=on_result)
        intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "fr-FR")
        intent.putExtra(RecognizerIntent.EXTRA_PROMPT, "Dictez une adresse complète")
        activity.startActivityForResult(intent, REQUEST_CODE)
        return True
    except Exception as exc:
        error_callback(f"Saisie vocale indisponible : {exc}")
        return False
