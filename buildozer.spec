# buildozer.spec for TransAs
# Generated for the TransAs delivery-route optimizer (see manifest.md).
#
# How to build (do NOT commit the .apk; buildozer writes build/ locally):
#     pip install buildozer
#     buildozer android debug          # builds bin/transas-0.1-armeabi-v7a-debug.apk

[app]

title = TransAs
package.name = transas
package.domain = fr.transas.app

# Source layout
source.dir = .
source.include_exts = py,png,jpg,jpeg,md,txt,kv,json

# Application version
version = 0.1
version.pattern = 0.1

# Kivy 2.3.1 includes the upstream GLES glShaderSource typedef correction
# (Kivy #8557 / PR #8917); Kivy 2.3.0 fails compiling cgl_gl.c with clang 17
# from NDK 28: incompatible function pointer types.
# Keep Cython and KivyMD pinned to the versions validated by the p4a recipe.
# Pillow 13.0.0 is built by the locally patched p4a recipe in this repository.
requirements = python3==3.11.11,cython==0.29.36,kivy==2.3.1,kivymd==1.1.1,requests,pillow==13.0.0,geopy,android

# Portrait orientation — one-handed use in the field.
orientation = portrait

# Cover / launch icon. scripts/prepare_cover.sh creates this file before build.
icon.filename = %(source.dir)s/cover/icon.png
# presplash.filename = %(source.dir)s/cover/presplash.jpg

# Android target
android.api = 34
android.minapi = 21
android.archs = arm64-v8a
android.release_artifact = apk

# SDK/NDK are project-local for developer builds; CI overrides these paths
# with the Android toolchain installed by setup-android@v4.
android.sdk_path = %(source.dir)s/.android-sdk
android.ndk_path = %(source.dir)s/.android-sdk/ndk/28.0.13004108

# Use the local python-for-android checkout. The release workflow patches
# Cython/Python selectors and links libc++ for NDK 28 before building.
# KivyMD 1.1.1 has no PyPI wheel: the local recipe builds it from the sdist
# instead of letting p4a's wheel-only resolver reject it.
p4a.local_recipes = %(source.dir)s/p4a-recipes
p4a.source_dir = %(source.dir)s/.local/python-for-android
android.skip_update = 1

# Runtime permissions used by networking and driver's location.
android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION
android.allow_backup = False
android.presplash_color = #FFFFFFFF
android.wakelock = False

# Release signing is enabled by the release workflow when secrets exist.
# android.keystore = %(source.dir)s/transas-release.jks
# android.keyalias = transas

[buildozer]
log_level = 1
warn_on_root = 1
