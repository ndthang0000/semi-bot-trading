from __future__ import annotations

from tempfile import TemporaryDirectory as _TemporaryDirectory
from typing import Any


def TemporaryDirectory(*args: Any, **kwargs: Any) -> _TemporaryDirectory:
    kwargs.setdefault("ignore_cleanup_errors", True)
    return _TemporaryDirectory(*args, **kwargs)
