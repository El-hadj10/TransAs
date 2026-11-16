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
# Keep the package identity already installed on the test device.  Changing
# either component makes Android treat the build as a separate application
# and prevents an in-place upgrade.
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
# CRITICAL PIN: Kivy 2.3.0 + KivyMD 1.1.1 are stable here with Python 3.11
# and Cython 0.29.36 when p4a recipes are aligned to the same python version.
# CRITICAL PIN (2026-07-13, ROLLBACK) : retour à ``Pillow==11.3.0`` après que
# la tentative de downgrade vers 10.2.0 ait cassé le build (4 rebuilds échoués).
# Le patch p4a local ``.local/python-for-android/pythonforandroid/recipes/Pillow/
# setup.py.patch`` est conçu pour Pillow 11.3.0 uniquement (lignes 156 et 514
# de setup.py) — les hunks ne s'appliquent pas à 10.2.0. Patcher la recipe p4a
# pour 10.2.0 = 1-2h d'investigation + 1-2 builds d'essai → non rentable.
#
# La vraie cause du SIGSEGV à fault address 0x28 (BUG-001) reste débattue :
# Pillow 11.x est suspecté mais pas prouvé. Les **fixes défensifs** (defer de
# ``kivy.core.image.Image`` et ``ui.services.folium_renderer`` dans
# ``ui/screens/map_screen.py``) + try/except bootstrap dans ``main.py`` sont
# **la vraie mitigation** : ils repoussent le load natif Pillow hors du chemin
# critique de SDLThread. Le downgrade Pillow était une **mesure conservative
# additionnelle**, pas le fix principal.
#
# Action de suivi si SIGSEGV persiste après ce rebuild :
#   1. Capturer ``/tmp/launch2.log`` et grep pour ``SIGSEGV`` + ``PyObject_Vectorcall``
#   2. Si Pillow 11.x CONFIRMÉ en cause → patcher la recipe p4a (cf. report_bug.md
#      "Actions de rebuild post-fix — Plan B")
#   3. Sinon → le problème est ailleurs (libjpeg p4a, NDK r25c, etc.)
#
# Référence complète : ``report_bug.md`` BUG-001 + section "Décision 2026-07-13".
#
# SUIVI CVE 2026-10-27 (NOUR) : ``requirements.txt`` est monté à Pillow==13.0.0
# (71 CVE OSV éteintes côté dev/CI — cf. pip-audit). MONTEE APK COMPLÈTE
# 2026-10-27 : le patch p4a a été réécrit pour setup.py 13.0.0 (3 hunks,
# sémantique identique : ren = tuple split(":"), pkg-config skippé, sys.prefix
# enlevé, guessing plateforme/standard /usr/local désactivés). Ancien patch
# 11.3.0 conservé : .local/python-for-android/.../recipes/Pillow/
# setup.py.patch.bak-11.3.0-2026-10-27. REBUILD DE VALIDATION RÉUSSI le
# 2026-10-27 21:30 : Pillow 13.0.0 cross-compilé depuis la source via le patch
# (pyproject: "Successfully built pillow-13.0.0-cp311-cp311-android_21_arm64_v8a.whl"),
# bundle arm64 vérifié (pillow-13.0.0.dist-info + tous les modules .so aarch64).
# APK test : bin/transas-0.1-arm64-v8a-debug.apk. Test d'installation sur
# appareil à faire (validation runtime).
# ``,android`` (the p4a recipe, NOT the ``androidx.*`` namespace) is needed for
# ``from android import activity`` in ``ui/services/speech.py`` so the
# "Ajouter par voix" entry point can use the Android RecognizerIntent
# bridge. Without it the import raises ImportError on APK and the button
# stays silently inert (the in-app try/except already hides the failure).
requirements = python3==3.11.11,cython==0.29.36,kivy==2.3.0,kivymd==1.1.1,requests,pillow==13.0.0,geopy,android

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
icon.filename = %(source.dir)s/cover/icon.png
# presplash.filename = %(source.dir)s/cover/presplash.jpg

# ---------------------------------------------------------------------------
# Android target
# ---------------------------------------------------------------------------
# API 34 (Android 14) as target — reaches Play Store's current-target window.
# API 21 (Android 5.0) as minimum — wide reach without sacrificing adaptive
# icons / scoped storage features.
android.api = 34
android.minapi = 21

# Build arm64 only for faster, more reliable local APK generation.
android.archs = arm64-v8a

# Buildozer 1.6 defaults to AAB for `android release`; force APK output so we
# can sideload and validate the exact release artifact on-device.
android.release_artifact = apk

# SDK location.
#
# Use a project-local SDK path so Buildozer can create and populate the
# Android toolchain in a writable location on this machine. The previous
# hardcoded /usr/local/lib/android path is not writable in this environment
# and causes the build to fail before the real Android packaging work starts.
android.sdk_path = %(source.dir)s/.android-sdk

# Use a project-local NDK path so Buildozer can populate the toolchain in a
# writable location. This avoids the permission issue on the old global path
# and keeps the SDK/NDK under the repository tree for local builds.
android.ndk_path = %(source.dir)s/.android-sdk/ndk/28.0.13004108

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
# THE surgical fix: the release workflow clones p4a, then patches recipe
# selectors to keep python3/hostpython3 and Cython aligned.
#
# The clone lives under source.dir so the same relative path works on local
# dev (`bash scripts/prepare_cover.sh && buildozer android debug`) after
# running the same `git clone + sed` from the workflow step manually.
p4a.source_dir = %(source.dir)s/.local/python-for-android

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
# ACCESS_FINE/COARSE_LOCATION (2026-10-27) power the "RÉOPTIMISER D'ICI" action:
# ``ui/services/location.py`` reads the driver's position once, then the
# controller reorders only the remaining stops. COARSE alone is enough when the
# driver only grants the approximate location (Android 12+ radio button).
# Both are runtime permissions: the app asks on first use, never at boot.
android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION

# Security hardening: disable Android cloud/device backup of app data.
android.allow_backup = False

# Explicit C++ runtime for the SDL2 bootstrap layer. The p4a bootstrap builds
# a small native C++ component (for example hid.cpp), and without an STL the
# linker leaves the operator new/delete symbols unresolved during the create
# step. This is the common cause of the linker failures seen in CI logs.
android.stl = c++_shared

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
log_level = 1
warn_on_root = 1
