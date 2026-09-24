"""Formatter settings the corpus is generated and checked under.

Kept free of imports from `pyproject_fmt_py` so `tools/extract_corpus.py` can read it from an
isolated environment that only has the reference implementation installed.
"""

from __future__ import annotations

from typing import Any

_BASE: dict[str, Any] = {
    "column_width": 120,
    "indent": 2,
    "keep_full_version": False,
    "max_supported_python": (3, 13),
    "min_supported_python": (3, 9),
    "generate_python_version_classifiers": False,
    "table_format": "short",
    "sub_table_spacing": "",
    "separate_root_table": "\n",
    "expand_tables": [],
    "collapse_tables": [],
    "skip_wrap_for_keys": [],
}

PROFILES: dict[str, dict[str, Any]] = {
    "short": dict(_BASE),
    "long": {**_BASE, "table_format": "long"},
    "keep-full-version": {**_BASE, "keep_full_version": True},
    "classifiers": {
        **_BASE,
        "generate_python_version_classifiers": True,
        "max_supported_python": (3, 15),
        "min_supported_python": (3, 10),
    },
    "narrow": {**_BASE, "column_width": 40},
}

#: Every case runs under these.
DEFAULT_PROFILES: tuple[str, ...] = ("short", "long")

#: Modules whose rules branch on a setting the default profiles hold fixed.
EXTRA_PROFILES: dict[str, tuple[str, ...]] = {
    "build_systems": ("keep-full-version",),
    "dependency_groups": ("keep-full-version",),
    "project": ("keep-full-version", "classifiers"),
    "main": ("classifiers", "narrow"),
}


def profiles_for(module: str) -> tuple[str, ...]:
    """Return the profile names the cases of `module` are generated under."""
    return DEFAULT_PROFILES + EXTRA_PROFILES.get(module, ())
