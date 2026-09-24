"""Laying a document out: widths, quotes, array breaking and the gaps between tables."""

from __future__ import annotations

from typing import Any

import pytest

from pyproject_fmt_py import Settings, format_toml
from pyproject_fmt_py.strings import encode_basic, encode_key_segment, encode_literal, fits_literal
from pyproject_fmt_py.width import columns, last_line_columns


def written(source: str, **settings: Any) -> str:
    base: dict[str, Any] = {
        "column_width": 120,
        "indent": 2,
        "generate_python_version_classifiers": False,
        "max_supported_python": (3, 13),
        "min_supported_python": (3, 9),
    }
    return format_toml(source, Settings(**{**base, **settings}))


@pytest.mark.parametrize(
    ("source", "want"),
    [
        ("[t]\nb=1\n", "[t]\nb = 1\n"),
        ("[t]\nb = 1 # note\n", "[t]\nb = 1  # note\n"),
        ("[t] # about\nb = 1\n", "[t]  # about\nb = 1\n"),
        ("[t]\nx=[1,2]\n", "[t]\nx = [ 1, 2 ]\n"),
        ("[t]\nx=[]\n", "[t]\nx = []\n"),
        ("[t]\nx=[[1,2],[3]]\n", "[t]\nx = [ [ 1, 2 ], [ 3 ] ]\n"),
        ("[t]\nx={a=1,b=2}\n", "[t]\nx = { a = 1, b = 2 }\n"),
        ("[t]\nx={}\n", "[t]\nx = {}\n"),
        ("[[t]]\nx = 1\n", "[[t]]\nx = 1\n"),
    ],
)
def test_lays_a_line_out(source, want):
    assert written(source) == want


@pytest.mark.parametrize(
    ("source", "want"),
    [
        ("[t]\na = 'plain'\n", '[t]\na = "plain"\n'),
        ('[t]\na = "has \\" quote"\n', "[t]\na = 'has \" quote'\n"),
        ("[t]\na = 'back\\slash'\n", "[t]\na = 'back\\slash'\n"),
        ('[t]\na = """multi\nline"""\n', '[t]\na = """multi\nline"""\n'),
    ],
)
def test_picks_the_plainest_spelling(source, want):
    assert written(source) == want


def test_removes_quotes_a_key_does_not_need():
    assert written('[tool."acme"]\n"line-length" = 1\n') == "[tool.acme]\nline-length = 1\n"


def test_a_key_holding_a_quote_stays_literal():
    assert written("[t]\n'say \"hi\"' = 1\n") == "[t]\n'say \"hi\"' = 1\n"


def test_a_literal_key_holding_a_backslash_gains_escapes():
    assert written("[t]\n'a\\b' = 1\n") == '[t]\n"a\\\\b" = 1\n'


def test_an_array_that_outgrows_the_column_breaks_with_a_trailing_comma():
    assert written('[t]\nx = ["aaaaaaaaaa", "bbbbbbbbbb"]\n', column_width=30) == (
        '[t]\nx = [\n  "aaaaaaaaaa",\n  "bbbbbbbbbb"\n]\n'
    )


def test_an_array_the_file_wrote_open_keeps_its_own_trailing_comma():
    assert written('[t]\nx = [\n  "a",\n]\n') == '[t]\nx = [\n  "a",\n]\n'


def test_a_member_comment_keeps_an_array_open():
    assert written('[t]\nx = ["a" # why\n]\n') == '[t]\nx = [\n  "a" # why\n]\n'


def test_member_comments_line_up_against_the_widest_member():
    source = '[t]\nx = [\n  "aa", # one\n  "b", # two\n]\n'
    assert written(source) == '[t]\nx = [\n  "aa", # one\n  "b",  # two\n]\n'


def test_a_comment_below_the_last_member_stays_there():
    assert written("[t]\nx = [\n  1,\n  # dangling\n]\n") == "[t]\nx = [\n  1,\n  # dangling\n]\n"


def test_root_tables_are_set_one_blank_line_apart():
    assert written("[a]\nx=1\n[b]\ny=2\n") == "[a]\nx = 1\n\n[b]\ny = 2\n"


def test_nothing_is_written_above_the_first_line():
    assert written("\n\n[a]\nx = 1\n") == "[a]\nx = 1\n"


def test_sub_tables_stay_adjacent_unless_asked_apart():
    source = "[tool.acme]\nx = 1\n[tool.acme.sub]\ny = 2\n"
    assert written(source, table_format="long") == source
    assert written(source, table_format="long", sub_table_spacing="\n") == (
        "[tool.acme]\nx = 1\n\n[tool.acme.sub]\ny = 2\n"
    )


def test_a_run_of_blank_lines_reads_as_one_gap():
    assert written("[t]\nx = 1\n\n\n\n\ny = 2\n") == "[t]\nx = 1\n\n\ny = 2\n"


def test_the_file_ends_where_a_line_ends():
    assert written("[t]\nx = 1") == "[t]\nx = 1\n"


@pytest.mark.parametrize(
    ("text", "width"),
    [("abc", 3), ("", 0), ("日本語", 6), ("á", 1), ("a\tb", 3)],
)
def test_measures_how_wide_text_is(text, width):
    assert columns(text) == width


def test_measures_only_the_line_a_value_ends_on():
    assert last_line_columns("aaa\nbb") == 2
    assert last_line_columns("aaa") == 3


@pytest.mark.parametrize(
    ("text", "held"),
    [("plain", True), ("has ' quote", False), ("with\ttab", True), ("with\nbreak", False)],
)
def test_says_what_a_literal_string_can_hold(text, held):
    assert fits_literal(text) is held


def test_writes_a_basic_string_with_the_escapes_toml_requires():
    assert encode_basic('a"b\\c\nd\x00') == '"a\\"b\\\\c\\nd\\u0000"'


def test_writes_a_literal_string_unless_it_cannot_hold_the_text():
    assert encode_literal("plain") == "'plain'"
    assert encode_literal("has ' quote") == '"has \' quote"'


@pytest.mark.parametrize(
    ("name", "written_as"),
    [("bare-1_a", "bare-1_a"), ("", '""'), ("a b", '"a b"'), ('say "hi"', "'say \"hi\"'")],
)
def test_writes_a_key_segment(name, written_as):
    assert encode_key_segment(name) == written_as
