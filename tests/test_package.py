"""What the package offers a caller that imports it."""

from __future__ import annotations

import pyproject_fmt_py


def test_version_is_available():
    assert pyproject_fmt_py.__version__


def test_the_formatter_is_what_the_package_exports():
    assert set(pyproject_fmt_py.__all__) <= set(dir(pyproject_fmt_py))
    assert pyproject_fmt_py.format_toml("[project]\nname='x'\n", pyproject_fmt_py.Settings())
