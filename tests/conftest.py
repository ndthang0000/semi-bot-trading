"""Pytest bootstrap for Python 3.10 compatibility.

- tomllib was added in 3.11; shim it with tomli on 3.10.
- datetime.UTC was added in 3.11; the live_worker source itself uses it via
  `from datetime import UTC` which works on the production VPS (3.11+), but the
  CI sandbox runs 3.10.  We patch sys.modules before any project import occurs.
"""
from __future__ import annotations

import sys

# ── tomllib shim ─────────────────────────────────────────────────────────────
if "tomllib" not in sys.modules:
    try:
        import tomllib  # noqa: F401 (3.11+)
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]
        sys.modules["tomllib"] = tomllib

# ── datetime.UTC shim ────────────────────────────────────────────────────────
import datetime as _dt
if not hasattr(_dt, "UTC"):
    _dt.UTC = _dt.timezone.utc  # type: ignore[attr-defined]
