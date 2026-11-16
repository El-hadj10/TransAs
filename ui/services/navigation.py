"""Platform bridge for opening the next stop in the user's maps app."""
from __future__ import annotations

import sys
import webbrowser

from ui.services.uri_utils import build_geo_uri, build_google_maps_web_url


def _is_android() -> bool:
    """Use Kivy's platform marker: CPython reports ``linux`` on Android."""
    try:
        from kivy.utils import platform
        return platform == "android"
    except Exception:
        return sys.platform == "android"


def open_navigation(lat: float, lon: float, label: str = "") -> bool:
    """Open an Android ``geo:`` intent, or Google Maps on desktop.

    Returns ``True`` once a hand-off was requested.  The Android chooser lets
    the driver select Google Maps, Waze, OsmAnd, or any compatible navigator.
    """
    if _is_android():
        try:
            from jnius import autoclass  # type: ignore[import-not-found]
            Intent = autoclass("android.content.Intent")
            Uri = autoclass("android.net.Uri")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            intent = Intent(Intent.ACTION_VIEW)
            intent.setData(Uri.parse(build_geo_uri(lat, lon, label)))
            PythonActivity.mActivity.startActivity(intent)
            return True
        except Exception:
            return False
    try:
        return bool(webbrowser.open(build_google_maps_web_url(lat, lon)))
    except Exception:
        return False
