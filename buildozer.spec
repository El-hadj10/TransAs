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
#
# CRITICAL PIN (iter-30): `cython==0.29.36` MUST appear BEFORE `kivy`. python-
# for-android reads the `requirements` line as its recipe-manifest; explicitly
# demanding cython==0.29.36 forces p4a's host-build phase to download the
# Cython 0.29.x track instead of letting p4a pull the latest Cython (3.x
# by recent default). Without this pin kivy 2.3.0's generated `_clock.c`
# emits an SDL2 callback invocation with 5 args where the binding expects
# 6, surfacing during compile as
#   `error: too few arguments to function call, expected 6, have 5`
# (the original iter-29 buildozer crash trace, GH Actions run 29195127402).
# This is THE root cause that survived 29 iterations; the rest of the
# pipeline (SDK layout, NDK env lock, symlink path aliases) was a long
# prelude to identifying the actual recipe mistake.
requirements = python3,cython==0.29.36,kivy==2.3.0,kivymd==1.1.1,requests,Pillow>=10.0.0,<11.0.0,geopy

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

# SDK location.
#
# CRITICAL FIX (iteration 22): hardcoded path rather than ``$ANDROIDSDK``
# env-var expansion.
#
# Why: buildozer loads this spec and runs ``os.path.expandvars()`` on
# string templates **once** at spec-load time (in the Python subprocess
# before python-for-android ever reads the value). When ``ANDROIDSDK``
# is missing from ``os.environ`` at that moment — which empirically
# happens on github-hosted runners even when bash-level ``export
# ANDROIDSDK=...`` runs in the same step — the literal ``$ANDROIDSDK``
# substring survives. python-for-android then concatenates it into paths
# like ``os.path.join('$ANDROIDSDK', 'tools', 'bin', 'sdkmanager')``,
# which surfaces as the misleading "Wrong version in preinstalled
# sdkmanager" warning followed by the
#   ClassNotFoundException: com.android.sdklib.tool.sdkmanager.SdkManagerCli
# that has blocked every run since iteration 11.
#
# Side-effect-free fix: hardcode the root that ``setup-android@v4``
# installs to on ubuntu-22.04 (verified by reading the action's
# ``action.yml`` and confirmed by the resolved ``ANDROID_HOME`` in past
# runs — log lines like ``::notice::✓ ANDROIDSDK=/usr/local/lib/android/sdk``
# match exactly). This bypasses both env-var substitution and the
# p4a ``$PATH`` fallback that mis-resolves ``APP_HOME`` on cmdline-tools
# 14.0.
#
# Local-dev override: replace this path with your own SDK install before
# ``buildozer android debug`` (typical values:
#   Linux   → $HOME/Android/Sdk
#   macOS   → $HOME/Library/Android/sdk
#   Windows → %USERPROFILE%\Android\Sdk
# ) AND export ``ANDROIDSDK`` / ``ANDROID_HOME`` / ``ANDROID_SDK_ROOT``
# / ``ANDROIDNDK`` in the same shell (see ``cover/README.md`` §
# "Tell Buildozer where the SDK and JDK live").
android.sdk_path = /usr/local/lib/android/sdk

# CRITICAL FIX (iteration 26): pin buildozer's NDK path so python-for-android
# uses the NDK we pre-installed via setup-android@v4 instead of bootstrapping
# its own. Iter-25 logs (GH Actions run 29191818397) revealed that without
# this pin, buildozer silently downloaded `android-ndk-r28c` into
# .buildozer/android/platform/android-ndk-r28c/ - discordant with the
# env's ANDROID_NDK_VERSION pin (25.2.9519653 / r25c) declared in
# .github/workflows/release.yml. With mismatched toolchains, p4a's
# cross-compile of hostpython3 / target-python / Kivy C-extensions crashed
# clang after ~13 minutes of compile. Pinning here forces buildozer to
# honor our pre-installed r25c (clang 14, binutils GNU) which is the
# version p4a's recipes are calibrated against.
# Local-dev override: replace with the matching NDK dir of your local SDK.
android.ndk_path = /usr/local/lib/android/sdk/ndk/25.2.9519653

# CRITICAL FIX (iteration 33): p4a recipe override — THE surgical fix.
#
# python-for-android (p4a) emits two hardcoded `pip3 install ... Cython<...>
# -q --upgrade` subprocess calls in its internal recipe bootstrap. Confirmed
# at buildozer-x86_64.log lines 19949 + 20130 of run 29196024717 (iter-30):
#   pip3 install ... Cython<3.2 -q --upgrade             (pyjnius-sdl2 buildout)
#   pip3 install ... Cython>=0.29,<3.1 -q --upgrade       (android-sdl2 buildout)
#
# These calls BYPASS every constraint, env var, and pip.conf set upstream
# (proven empirically: iter-30 spec pin ignored, iter-31 PIP_CONSTRAINT
# ignored, iter-32 pip.conf ignored). Cython 3.x gets installed anyway and
# collides with Kivy 2.3.0's generated `_clock.c` at clang compile, surfacing
# as `error: too few arguments to function call, expected 6, have 5`.
#
# THE surgical fix: the iter-33 release.yml step clones p4a, sed-patches
# BOTH hardcoded selectors to a strict `Cython==0.29.36` (the exact version
# Kivy 2.3.0's _clock.pyx was generated against), then points buildozer at
# the patched clone via this `android.p4a_dir`. Patched p4a's bootstrap
# resolves OUR selector and CANNOT upgrade past it.
#
# The clone lives under source.dir so the same relative path works on local
# dev (`bash scripts/prepare_cover.sh && buildozer android debug`) after
# running the same `git clone + sed` from the workflow step manually.
android.p4a_dir = %(source.dir)s/.local/python-for-android

# CRITICAL FIX (iteration 20):
# Disable p4a's internal sdkmanager invocation. The p4a wrapper script
# has a hardcoded classpath that fails to resolve SdkManagerCli when
# cmdline-tools version >= 14.0 is in use. Since we pre-install all
# required SDK components via setup-android@v4 (which correctly handles
# the classpath), p4a's update check is redundant and only causes:
#   ClassNotFoundException: com.android.sdklib.tool.sdkmanager.SdkManagerCli
# Setting android.skip_update = 1 tells p4a to trust the pre-installed SDK
# and skip its own sdkmanager invocation entirely.
android.skip_update = 1

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
