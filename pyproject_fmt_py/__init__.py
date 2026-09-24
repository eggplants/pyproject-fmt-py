""".. include:: ../README.md"""

from __future__ import annotations

import importlib.metadata

from .config import Settings, TableShape
from .errors import FormatError
from .formatter import format_toml

try:
    __version__ = importlib.metadata.version(__name__)
except importlib.metadata.PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"

__all__ = [
    "FormatError",
    "Settings",
    "TableShape",
    "__version__",
    "format_toml",
]
