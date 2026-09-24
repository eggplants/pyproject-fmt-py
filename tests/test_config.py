"""What the settings accept, and which tables they fold."""

from __future__ import annotations

import pytest

from pyproject_fmt_py.config import Settings, TableShape


def test_defaults_are_accepted():
    settings = Settings()
    assert settings.column_width == 120
    assert settings.table_format == "short"


@pytest.mark.parametrize(
    "build",
    [
        lambda: Settings(max_supported_python=(4, 0)),
        lambda: Settings(min_supported_python=(4, 0)),
    ],
    ids=["max", "min"],
)
def test_rejects_a_python_other_than_3(build):
    with pytest.raises(ValueError, match="only Python 3 is supported"):
        build()


@pytest.mark.parametrize(
    "build",
    [
        lambda: Settings(expand_tables=["[nope]"]),
        lambda: Settings(collapse_tables=["[nope]"]),
    ],
    ids=["expand", "collapse"],
)
def test_rejects_a_selector_that_is_not_a_table_name(build):
    with pytest.raises(ValueError, match="is not a table name"):
        build()


def test_rejects_a_blank_skip_wrap_key():
    with pytest.raises(ValueError, match="not nothing"):
        Settings(skip_wrap_for_keys=["  "])


def test_shape_follows_table_format():
    assert Settings(table_format="short").table_shape.should_collapse(("tool", "ruff"))
    assert not Settings(table_format="long").table_shape.should_collapse(("tool", "ruff"))


def test_the_closest_selector_decides():
    settings = Settings(table_format="short", expand_tables=["tool.ruff"], collapse_tables=["tool.ruff.lint"])
    shape = settings.table_shape
    assert shape.should_collapse(("tool", "mypy"))
    assert not shape.should_collapse(("tool", "ruff"))
    assert not shape.should_collapse(("tool", "ruff", "format"))
    assert shape.should_collapse(("tool", "ruff", "lint"))
    assert shape.should_collapse(("tool", "ruff", "lint", "isort"))


def test_a_quoted_name_holding_a_dot_is_not_cut_in_half():
    shape = Settings(table_format="long", collapse_tables=['tool."a.b"']).table_shape
    assert shape.should_collapse(("tool", "a.b"))
    assert not shape.should_collapse(("tool", "a", "b"))


def test_shape_can_be_built_on_its_own():
    shape = TableShape(default_collapse=False, expand=frozenset(), collapse=frozenset({("x",)}))
    assert shape.should_collapse(("x", "y"))
    assert not shape.should_collapse(("y",))
