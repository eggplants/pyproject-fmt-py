"""Turning a commented-out key back on so it sorts with its table, and back off afterwards."""

from __future__ import annotations

from typing import Any

import pytest

from pyproject_fmt_py import Settings, format_toml
from pyproject_fmt_py.disabled import MARKER, enable, fresh_marker, standing_comment_lines
from pyproject_fmt_py.settings_file import settings_in


def written(source: str, **settings: Any) -> str:
    base: dict[str, Any] = {
        "column_width": 120,
        "generate_python_version_classifiers": False,
        "max_supported_python": (3, 13),
        "min_supported_python": (3, 9),
    }
    return format_toml(source, Settings(**{**base, **settings}))


def test_the_marker_is_one_the_source_does_not_hold():
    assert fresh_marker("nothing") == MARKER
    assert fresh_marker(f"# {MARKER}") == MARKER + "x"
    assert fresh_marker(f"# {MARKER}x") == MARKER + "xx"


def test_a_comment_where_a_key_could_stand_is_turned_on():
    held = enable("[t]\n# b = 1\na = 2\n", MARKER)
    assert held is not None
    assert held.splitlines()[1] == f"b = 1  # {MARKER}"


def test_a_comment_inside_an_array_is_left_alone():
    assert enable("[t]\nx = [\n  1,\n  # key = 2\n]\n", MARKER) is None


def test_a_comment_inside_a_multi_line_string_is_left_alone():
    assert enable('[t]\nx = """\n# key = 2\n"""\n', MARKER) is None


def test_a_commented_header_holds_the_run_below_it():
    assert enable("[t]\n# [other]\n# b = 1\n", MARKER) is None


def test_prose_is_left_as_prose():
    assert enable("[t]\n# just a note\na = 1\n", MARKER) is None


def test_a_value_spread_over_comment_lines_is_read_as_one():
    held = enable("[t]\n# x = [\n#   1,\n# ]\na = 2\n", MARKER)
    assert held is not None
    assert held.splitlines()[0] == "[t]"
    assert MARKER in held


def test_a_comment_the_file_already_wrote_beside_the_key_is_kept():
    held = enable("[t]\n# b = 1 # why\na = 2\n", MARKER)
    assert held is not None
    assert held.splitlines()[1].endswith(f"{MARKER}-kept")


def test_standing_comments_are_the_ones_where_a_key_could_stand():
    source = "# one\n[t]\nx = [\n  # two\n]\n# three\n"
    assert standing_comment_lines(source) == {0, 5}


def test_a_disabled_key_sorts_with_its_table():
    assert written("[tool.autopep8]\nrecursive = true\n# max_line_length = 100\n") == (
        "[tool.autopep8]\n# max_line_length = 100\nrecursive = true\n"
    )


def test_a_disabled_key_comes_back_as_a_comment():
    # the value is laid out but not sorted: what the comment says is what the file wrote there
    source = '[tool.autopep8]\n# select = ["E501","E302"]\nrecursive = true\n'
    assert written(source) == '[tool.autopep8]\nrecursive = true\n# select = [ "E501", "E302" ]\n'


def test_formatting_a_disabled_key_twice_changes_nothing():
    source = '[tool.autopep8]\n# select = ["E501","E302"]\nrecursive = true\n'
    once = written(source)
    assert written(once) == once


def test_a_disabled_alternative_beside_the_active_key_is_kept():
    source = '[project]\nname = "active"\n# name = "alternative"\n'
    assert written(source) == '[project]\nname = "active"\n# name = "alternative"\n'


def test_the_settings_a_table_holds_are_read():
    assert settings_in("[tool.x]\na = 1\n", ("tool", "x")) == {"a": 1}
    assert settings_in("[tool.x]\na = 1\n", ("tool", "y")) is None


def test_a_settings_path_that_names_no_table_is_refused():
    with pytest.raises(TypeError, match="is not a table"):
        settings_in("[tool]\nx = 1\n", ("tool", "x"))
    with pytest.raises(TypeError, match="not a table"):
        settings_in("[tool]\nx = 1\n", ("tool", "x", "y"))


def test_text_that_is_not_a_document_is_refused():
    with pytest.raises(SyntaxError):
        settings_in("[unterminated\n")
