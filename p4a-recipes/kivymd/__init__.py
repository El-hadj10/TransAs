"""KivyMD recipe for python-for-android.

KivyMD 1.1.1 is only published on PyPI as an sdist (no wheel). p4a resolves
non-recipe requirements with ``pip install --only-binary=:all:``, so it fails
with ``No matching distribution found for kivymd==1.1.1`` before it ever
reaches the target install step (CI run 44096850479).

Shipping a recipe makes p4a build the sdist into a wheel for the Android
platform and unpack it in the distribution, which is the supported path for a
pure-Python dependency without wheels. KivyMD 2.0.0 does ship a wheel but
renames every widget class the app uses, so downgrading is not an option.
"""

from pythonforandroid.recipe import PyProjectRecipe


class KivyMDRecipe(PyProjectRecipe):
    version = "1.1.1"
    url = (
        "https://files.pythonhosted.org/packages/35/55/"
        "d979644cdc9070a9611ab023db986aa0d540fc8f5fdd2c0f49eaef558751/"
        "kivymd-{version}.tar.gz"
    )
    # KivyMD imports Kivy at runtime and Pillow for its image handling.
    depends = ["kivy", "pillow"]
    # Its pyproject pins exact build deps (setuptools~=69.2.0, wheel~=0.44.0,
    # packaging~=24.0) that p4a's hostpython does not carry; p4a builds with
    # --no-isolation, where `python -m build` refuses to start. The package is
    # pure Python, so skipping that check is safe.
    extra_build_args = ["--skip-dependency-check"]


recipe = KivyMDRecipe()
