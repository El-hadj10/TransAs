"""Root conftest — ensures the project root is importable for tests.

With `__init__.py` files in every package, pytest does NOT auto-insert
the rootdir on `sys.path`. This conftest adds it explicitly so tests can
do `from core import geocoder`.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
