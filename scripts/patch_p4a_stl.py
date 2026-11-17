#!/usr/bin/env python3
"""Make the p4a toolchain build with NDK 28 / clang 19.

Two families of failure are patched here:

* Linking: the NDK dropped libstdc++ in r27. python-for-android still relies
  on the legacy ndk-build `system` STL default and on meson cross files whose
  link arguments come from LDFLAGS, which leaves C++ symbols (`operator new`,
  `std::__ndk1::*`, `__cxa_*`) and libm (`sincosf`, `powf`) unresolved in
  libSDL2.so / libthorvg-1.so.
* Compiling: clang 19 promotes -Wincompatible-function-pointer-types to an
error, which Kivy's Cython-generated cgl_gl.c trips on glShaderSource, so
  the kivy recipe needs -Wno-error there (plus the host pkg-config guard that
  otherwise leaks /usr/include into the Android cross build).

Run this after cloning p4a and before invoking buildozer:

    python scripts/patch_p4a_stl.py .local/python-for-android

CI (.github/workflows/release.yml) runs the same script, so local and CI
builds use an identical toolchain patch. The function is idempotent.
"""

from __future__ import annotations

import sys
from pathlib import Path

APP_STL_LINE = "APP_STL := c++_shared"
APP_LDFLAGS_LINE = "APP_LDFLAGS += -lc++_shared"
KIVY_MARKER = "_Kivy_get_recipe_env_ndk28"
THORVG_MARKER = "_LibThorVG_get_recipe_env_libcxx_lm"

KIVY_OVERRIDE = '''

# TransAs (2026-11-17): NDK 28 ships clang 19, which makes
# -Wincompatible-function-pointer-types an error. Kivy's Cython-generated
# kivy/graphics/cgl_backend/cgl_gl.c fails on glShaderSource (run 43959672592),
# so downgrade both spellings of that diagnostic to a warning. Also stop the
# host pkg-config from leaking /usr/include headers into the cross build.
_Kivy_get_recipe_env = KivyRecipe.get_recipe_env


def _Kivy_get_recipe_env_ndk28(self, arch, **kwargs):
    env = _Kivy_get_recipe_env(self, arch, **kwargs)
    cflags = env.get("CFLAGS", "")
    for flag in (
        "-Wno-error=incompatible-function-pointer-types",
        "-Wno-incompatible-function-pointer-types",
    ):
        if flag not in cflags:
            cflags += " " + flag
    env["CFLAGS"] = cflags
    env["PKG_CONFIG"] = "/bin/false"
    env["PKG_CONFIG_PATH"] = ""
    env["PKG_CONFIG_LIBDIR"] = self.get_build_dir(arch.arch)
    return env


KivyRecipe.get_recipe_env = _Kivy_get_recipe_env_ndk28
'''

THORVG_OVERRIDE = '''

# TransAs (2026-11-16): MesonRecipe writes the cross-file link arguments from
# env LDFLAGS only. NDK r27+ ships no libstdc++, and libthorvg's own meson
# files do not pull libm, so both must be linked explicitly: run 43953118690
# failed on std::__ndk1::* / __cxa_*, then run 43956775611 on sincosf/tanf.
_LibThorVG_get_recipe_env = LibThorVGRecipe.get_recipe_env


def _LibThorVG_get_recipe_env_libcxx_lm(self, arch, **kwargs):
    env = _LibThorVG_get_recipe_env(self, arch, **kwargs)
    ldflags = env.get("LDFLAGS", "")
    for flag in ("-lc++_shared", "-lm"):
        if flag not in ldflags:
            ldflags += " " + flag
    env["LDFLAGS"] = ldflags
    return env


LibThorVGRecipe.get_recipe_env = _LibThorVG_get_recipe_env_libcxx_lm
'''


def patch_application_mk(path: Path) -> bool:
    """Force APP_STL/APP_LDFLAGS into one bootstrap Application.mk."""
    text = path.read_text()
    lines = [APP_STL_LINE if line.startswith("# APP_STL :=") else line
             for line in text.splitlines()]
    text = "\n".join(lines) + "\n"
    if APP_STL_LINE not in text.splitlines():
        text += APP_STL_LINE + "\n"
    if APP_LDFLAGS_LINE not in text.splitlines():
        text += APP_LDFLAGS_LINE + "\n"
    if text != path.read_text():
        path.write_text(text)
        return True
    return False


def patch_kivy(recipe: Path) -> bool:
    """Allow Kivy's generated C to compile under clang 19."""
    text = recipe.read_text()
    if KIVY_MARKER in text:
        return False
    if "class KivyRecipe" not in text:
        raise SystemExit(f"::error::{recipe} does not define KivyRecipe")
    recipe.write_text(text + KIVY_OVERRIDE)
    return True


def patch_thorvg(recipe: Path) -> bool:
    """Add -lc++_shared to the libthorvg meson recipe environment."""
    text = recipe.read_text()
    if THORVG_MARKER in text:
        return False
    if "class LibThorVGRecipe" not in text:
        raise SystemExit(f"::error::{recipe} does not define LibThorVGRecipe")
    recipe.write_text(text + THORVG_OVERRIDE)
    return True


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_p4a_stl.py <python-for-android checkout>", file=sys.stderr)
        return 2

    p4a = Path(sys.argv[1])
    bootstraps = p4a / "pythonforandroid" / "bootstraps"
    thorvg = p4a / "pythonforandroid" / "recipes" / "libthorvg" / "__init__.py"
    kivy = p4a / "pythonforandroid" / "recipes" / "kivy" / "__init__.py"
    if not bootstraps.is_dir() or not thorvg.is_file() or not kivy.is_file():
        print(f"::error::{p4a} is not a python-for-android checkout", file=sys.stderr)
        return 3

    app_mks = sorted(bootstraps.rglob("Application.mk"))
    patched = [mk for mk in app_mks if patch_application_mk(mk)]
    thorvg_patched = patch_thorvg(thorvg)
    kivy_patched = patch_kivy(kivy)

    # A silently skipped file is how the first two attempts failed: verify the
    # lines are really present instead of trusting the write.
    missing = [str(mk) for mk in app_mks
               if APP_LDFLAGS_LINE not in mk.read_text().splitlines()]
    if missing:
        print("::error::APP_LDFLAGS missing from: " + ", ".join(missing), file=sys.stderr)
        return 4
    if THORVG_MARKER not in thorvg.read_text():
        print("::error::libthorvg override did not land", file=sys.stderr)
        return 5
    if KIVY_MARKER not in kivy.read_text():
        print("::error::kivy clang-19 override did not land", file=sys.stderr)
        return 6

    print(f"p4a STL patch: {len(app_mks)} Application.mk files "
          f"({len(patched)} changed), libthorvg "
          f"{'patched' if thorvg_patched else 'already patched'}, kivy "
          f"{'patched' if kivy_patched else 'already patched'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
