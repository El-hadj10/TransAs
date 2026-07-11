# buildozer.spec for TransAs
# Generated for the TransAs delivery-route optimizer (see manifest.md).
#
# How to build (do NOT commit the .apk; buildozer writes build/ locally):
#     pip install buildozer
#     buildozer android debug          # builds bin/transas-0.1-armeabi-v7a-debug.apk

[app]

# Packaging identity on the device
title = TransAs
package.name = transas
# Use a France-localised, app-qualified domain: bare ``org.transas`` would
# collide with any future app claiming that namespace. ``fr.transas.app`` is
# unique today and readable on the launcher.
package.domain = fr.transas.app

# Source layout
source.dir = .
# Include the cover JPEG inside the APK assets (so icon.filename is reachable).
source.include_exts = py,png,jpg,jpeg,md,txt,kv,json

# Iteration 1
version = 0.1
version.pattern = 0.1

# Pure-Python deps only. OR-Tools / scipy.optimize / C++ bindings are excluded to
# keep the APK size + buildozer recipe list short (cf. structure.md Step 1.4).
# Pinned versions: kivymd's p4a recipe has been brittle across versions; locking
# to known-working (kivy 2.3.0, kivymd 1.1.1) keeps the build matrix stable.
#
# Pillow is required at runtime by ``ui.services.folium_renderer`` (offline
# route map PNG). The version pin matches ``requirements.txt`` and is the
# line whose p4a recipe builds cleanly on NDK r26d. ``geopy`` is retained
# for ``requirements.txt`` parity (size impact negligible).
requirements = python3,kivy==2.3.0,kivymd==1.1.1,requests,Pillow>=10.0.0,<11.0.0,geopy

# Portrait orientation — one-handed use in the field (cf. manifest.md §2).
orientation = portrait

# ---------------------------------------------------------------------------
# Cover / launch icon
# ---------------------------------------------------------------------------
# ``cover/file.enc`` is actually a JFIF/JPEG (header ``FF D8 FF E0 ... JFIF``,
# Photoshop EXIF) — just badly named. **Before the first ``buildozer android
# debug``**, run ``scripts/prepare_cover.sh`` (or simply ::
#     cp cover/file.enc cover/icon.jpg
# ). Skip this and Buildozer aborts with a confusing "icon not found" error.
#
# No separate ``presplash.filename`` here on purpose: a launcher icon squashed
# into a full-screen splash looks wrong. Drop a dedicated 1280×1920 splash at
# ``cover/presplash.jpg`` later and uncomment the line below when you do.
icon.filename = %(source.dir)s/cover/icon.jpg
# presplash.filename = %(source.dir)s/cover/presplash.jpg

# ---------------------------------------------------------------------------
# Android target
# ---------------------------------------------------------------------------
# API 34 (Android 14) as target — reaches Play Store's current-target window.
# API 21 (Android 5.0) as minimum — wide reach without sacrificing adaptive
# icons / scoped storage features.
android.api = 34
android.minapi = 21

# SDK location. We rely on Buildozer's documented env-var expansion: the
# leading ``$`` token is replaced with the value of the ``ANDROIDSDK``
# env var at invocation time (an unset env var expands to an empty
# string, producing Buildozer's misleading "Android SDK not found"
# — much clearer than a Python-template ``KeyError``). You MUST
# ``export ANDROIDSDK=$HOME/Android/Sdk`` before invoking buildozer
# (see ``cover/README.md`` § "Tell Buildozer where the SDK and JDK
# live" for interactive vs non-interactive-shell recipes).
android.sdk_path = $ANDROIDSDK

# INTERNET is required for Nominatim (address -> GPS) and OSRM (distance matrix).
# ACCESS_NETWORK_STATE lets Kivy / requests detect offline mode gracefully.
android.permissions = INTERNET,ACCESS_NETWORK_STATE

# Solid white background behind the launcher icon (matches the cover).
android.presplash_color = #FFFFFFFF

# Network access profile — we keep the screen alive only while the driver
# explicitly navigates a tour; default Wakelock stays off.
android.wakelock = False

# ---------------------------------------------------------------------------
# Release signing — Path A (sideload via GitHub Releases)
# ---------------------------------------------------------------------------
# After running ``bash scripts/setup_keystore.sh``, a ``transas-release.jks``
# file lives at the project root (NEVER committed — see ``.gitignore``).
# Uncomment the two fields below to make all subsequent builds sign with this
# stable release keystore. Without it, ``buildozer android debug`` falls back
# to its throwaway debug keystore — which Android then refuses to upgrade
# from, locking users into the very first APK they install.
#
# Passwords are NOT in this file. Buildozer reads them from environment vars
# (per p4a ``build.py``):
#   P4A_RELEASE_KEYSTORE_PASSWD   — unlock the keystore
#   P4A_RELEASE_KEY_PASSWD        — unlock the specific key (often same)
#   P4A_RELEASE_KEYALIAS          — alias name (default of setup_keystore.sh: transas)
#
# In CI (GitHub Actions → Settings → Secrets and variables → Actions), set:
#   KEYSTORE_BASE64      ← base64 -w 0 transas-release.jks
#   KEYSTORE_PASSWORD    ← P4A_RELEASE_KEYSTORE_PASSWD
#   KEY_ALIAS            ← P4A_RELEASE_KEYALIAS (default: transas)
#   KEY_PASSWORD         ← P4A_RELEASE_KEY_PASSWD
#
# android.keystore = %(source.dir)s/transas-release.jks
# android.keyalias = transas

# ---------------------------------------------------------------------------
# Build settings
# ---------------------------------------------------------------------------
[buildozer]
log_level = 2
warn_on_root = 1
