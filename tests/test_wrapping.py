"""Wrapping a string that outgrows the column, and the key patterns that hold one back."""

from __future__ import annotations

import pytest

from pyproject_fmt_py.wrapping import matches_key, read_pattern, wrap_with_continuations


@pytest.mark.parametrize(
    ("pattern", "segments"),
    [
        ("a.b", ("a", "b")),
        ("*", (None,)),
        ("*.commands", (None, "commands")),
        ("tool.ruff.*", ("tool", "ruff", None)),
        ('tool."a.b".commands', ("tool", "a.b", "commands")),
        ("not a key", ("not a key",)),
    ],
)
def test_reads_a_pattern(pattern, segments):
    assert read_pattern(pattern) == segments


@pytest.mark.parametrize(
    ("pattern", "path", "held"),
    [
        ("a.b", ("a", "b"), True),
        ("a.b", ("a", "b", "c"), False),
        ("a.b", ("a",), False),
        ("*.commands", ("tool", "tox", "commands"), True),
        ("*.commands", ("commands",), False),
        ("tool.ruff.*", ("tool", "ruff", "lint"), True),
        ("tool.ruff.*", ("tool", "mypy", "lint"), False),
        ("a.*.c", ("a", "b", "c"), True),
        ("a.*.c", ("a", "b", "d"), False),
    ],
)
def test_says_whether_a_pattern_names_a_key(pattern, path, held):
    assert matches_key(path, read_pattern(pattern)) is held


def test_breaks_after_a_classifier_separator():
    written = wrap_with_continuations("Programming Language :: Python :: Implementation :: CPython", 40, "  ")
    assert written is not None
    assert written.splitlines()[1].endswith("Python :: \\")


def test_breaks_after_a_space_where_there_is_no_separator():
    written = wrap_with_continuations("one two three four five six seven eight", 20, "  ")
    assert written is not None
    assert all(len(line) <= 20 for line in written.splitlines()[1:])


def test_breaks_wherever_the_width_runs_out_when_nothing_else_offers():
    written = wrap_with_continuations("a" * 60, 20, "  ")
    assert written is not None
    assert all(len(line) <= 20 for line in written.splitlines()[1:])


def test_a_column_with_no_room_for_the_form_gives_nothing_back():
    assert wrap_with_continuations("text", 1, "  ") is None


def test_what_is_written_opens_and_closes_a_multi_line_string():
    written = wrap_with_continuations("one two three four five six", 20, "  ")
    assert written is not None
    assert written.startswith('"""\\\n')
    assert written.endswith('"""')
