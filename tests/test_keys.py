"""Reading and writing key paths."""

from __future__ import annotations

import pytest

from pyproject_fmt_py.keys import is_under, parse_key_path, render_key, render_segment


@pytest.mark.parametrize(
    ("name", "segments"),
    [
        ("bare", ("bare",)),
        ("tool.ruff", ("tool", "ruff")),
        ("a.b.c", ("a", "b", "c")),
        ('a."b.c"', ("a", "b.c")),
        ("'x y'", ("x y",)),
        ('tool."a.b".c', ("tool", "a.b", "c")),
    ],
)
def test_parses_a_key_path(name, segments):
    assert parse_key_path(name) == segments


@pytest.mark.parametrize("name", ["", "a = 1", "[x]", "a # c", "a.", '"unterminated'])
def test_rejects_text_that_is_not_a_key_path(name):
    with pytest.raises(ValueError, match=r".+"):
        parse_key_path(name)


@pytest.mark.parametrize(
    ("segments", "text"),
    [
        (("tool", "ruff"), "tool.ruff"),
        (("a", "b.c"), 'a."b.c"'),
        (("x y",), '"x y"'),
        (("",), '""'),
        ((r"path\to",), r'"path\\to"'),
        (('say "hi"',), "'say \"hi\"'"),  # a name holding a quote stays out of escapes
    ],
)
def test_renders_a_key_path(segments, text):
    assert render_key(segments) == text


def test_a_rendered_path_reads_back_as_itself():
    for segments in [("tool", "a.b", "c"), ("x y", "z"), ("", "a")]:
        assert parse_key_path(render_key(segments)) == segments


def test_renders_one_segment():
    assert render_segment("a-b_1") == "a-b_1"
    assert render_segment("a b") == '"a b"'


@pytest.mark.parametrize(
    ("name", "prefix", "held"),
    [
        (("tool", "ruff"), ("tool",), True),
        (("tool", "ruff"), ("tool", "ruff"), True),
        (("tool",), ("tool", "ruff"), False),
        (("tool", "ruffx"), ("tool", "ruff"), False),
    ],
)
def test_says_whether_a_name_sits_under_a_prefix(name, prefix, held):
    assert is_under(name, prefix) is held
