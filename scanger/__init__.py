"""Scanger package.

Source files are grouped into subfolders. Those folders are on this package's
search path, so imports stay ``scanger.<module>`` (for example ``scanger.api``).
"""

from pathlib import Path

_root = Path(__file__).resolve().parent
for _name in ("app", "data", "vision", "discovery"):
    _entry = str(_root / _name)
    if _entry not in __path__:
        __path__.append(_entry)
