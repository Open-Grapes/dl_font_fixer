"""System calls the app needs, for the computer it runs on: winwin.py (Windows) or macapi.py (macOS).
Both offer the same names: is_admin, recycle, find_in_recycle_bin, move_back, lockers, reveal, ..."""

import os

IS_WIN = os.name == "nt"

if IS_WIN:
    from .winwin import *  # noqa: F401,F403
else:
    from .macapi import *  # noqa: F401,F403
