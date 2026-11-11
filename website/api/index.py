"""Vercel entry point: every /api/* request is routed here (vercel.json rewrites). The code lives in api/_lib/
(files starting with "_" are not turned into separate functions)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _lib.app import app  # noqa: E402,F401
