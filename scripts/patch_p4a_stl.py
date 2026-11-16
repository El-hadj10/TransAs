#!/usr/bin/env python3
"""Pin every p4a build to libc++ so NDK >= 27 links succeed.

The NDK dropped libstdc++ in r27. python-for-android still relies on the
legacy ndk-build `system` STL default and on meson cross files whose link
arguments come from LDFLAGS, which leaves C++ symbols (`operator new`,
`std::__ndk1::*`, `__cxa_*`) unresolved in libSDL2.so / libthorvg-1.so.

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
THORVG_MARKER = "_LibThorVG_get_recipe_env_libcxx"

THORVG_OVERRIDE = '''

# TransAs (2026-11-16): MesonRecipe writes the cross-file link arguments from
# env LDFLAGS; NDK r27+ ships no libstdc++, so link libc++_shared explicitly.
_LibThorVG_get_recipe_env = LibThorVGRecipe.get_recipe_env


def _LibThorVG_get_recipe_env_libcxx(self, arch, **kwargs):
    env = _LibThorVG_get_recipe_env(self, arch, **kwargs)
    if "-lc++_shared" not in env.get("LDFLAGS", ""):
        env["LDFLAGS"] = env.get("LDFLAGS", "") + " -lc++_shared"
    return env


LibThorVGRecipe.get_recipe_env = _LibThorVG_get_recipe_env_libcxx
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
    if not bootstraps.is_dir() or not thorvg.is_file():
        print(f"::error::{p4a} is not a python-for-android checkout", file=sys.stderr)
        return 3

    app_mks = sorted(bootstraps.rglob("Application.mk"))
    patched = [mk for mk in app_mks if patch_application_mk(mk)]
    thorvg_patched = patch_thorvg(thorvg)

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

    print(f"p4a STL patch: {len(app_mks)} Application.mk files "
          f"({len(patched)} changed), libthorvg "
          f"{'patched' if thorvg_patched else 'already patched'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
