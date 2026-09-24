"""Reading a source into the document model."""

from __future__ import annotations

import pytest

from pyproject_fmt_py.document import Array, InlineTable, Scalar, parse
from pyproject_fmt_py.errors import FormatError


def test_rejects_text_that_is_not_a_document():
    with pytest.raises(FormatError):
        parse("[unterminated\n")


def test_reads_root_entries_before_the_first_header():
    document = parse("a = 1\n[t]\nb = 2\n")
    assert [entry.key for entry in document.root] == [("a",)]
    assert [section.name for section in document.sections] == [("t",)]


def test_a_dotted_key_is_one_entry():
    (entry,) = parse("a.b.c = 1\n").root
    assert entry.key == ("a", "b", "c")


def test_a_quoted_segment_keeps_its_dot():
    (entry,) = parse('a."b.c" = 1\n').root
    assert entry.key == ("a", "b.c")


def test_a_header_with_no_table_of_its_own_opens_no_section():
    document = parse("[a.b]\nx = 1\n")
    assert [section.name for section in document.sections] == [("a", "b")]


def test_an_array_of_tables_repeats_its_name():
    document = parse("[[a]]\nx = 1\n\n[[a]]\ny = 2\n")
    assert [(section.name, section.kind) for section in document.sections] == [(("a",), "array")] * 2
    assert len(document.sections_named(("a",))) == 2


def test_comments_attach_to_what_sits_below_them():
    document = parse("# about the table\n[t]\n# about the key\nx = 1\n")
    assert document.sections[0].lead == ["# about the table"]
    assert document.sections[0].entries[0].lead == ["# about the key"]


def test_a_comment_below_the_last_entry_is_the_document_trailing():
    document = parse("[t]\nx = 1\n# the end\n")
    assert document.trailing == ["# the end"]


def test_blank_lines_are_kept_as_empty_pieces():
    document = parse("[t]\nx = 1\n\n\n# note\ny = 2\n")
    assert document.sections[0].entries[1].lead == ["", "", "# note"]


def test_a_trailing_comment_belongs_to_its_own_line():
    document = parse("[t]  # about\nx = 1 # also\n")
    assert document.sections[0].comment == "# about"
    assert document.sections[0].entries[0].comment == "# also"


def test_an_array_keeps_its_members_comments_and_trailing_comma():
    (entry,) = parse("x = [\n  # lead\n  1, # beside\n  2,\n  # dangling\n]\n").root
    value = entry.value
    assert isinstance(value, Array)
    assert [member.lead for member in value.members] == [["# lead"], []]
    assert [member.comment for member in value.members] == ["# beside", None]
    assert value.trailing == ["# dangling"]
    assert value.trailing_comma is True


def test_a_one_line_array_has_no_trailing_comma_and_no_own_lines():
    (entry,) = parse("x = [1, 2]\n").root
    assert isinstance(entry.value, Array)
    assert entry.value.trailing_comma is False
    assert [member.own_line for member in entry.value.members] == [False, False]


def test_a_member_on_its_own_line_says_so():
    (entry,) = parse("x = [\n  1,\n  2\n]\n").root
    assert isinstance(entry.value, Array)
    assert [member.own_line for member in entry.value.members] == [True, True]


def test_a_blank_line_inside_an_array_is_kept():
    (entry,) = parse("x = [\n  1,\n\n  2,\n]\n").root
    assert isinstance(entry.value, Array)
    assert entry.value.members[1].lead == [""]


def test_an_inline_table_reads_as_entries():
    (entry,) = parse('x = { a = 1, b.c = "t" }\n').root
    value = entry.value
    assert isinstance(value, InlineTable)
    assert [held.key for held in value.entries] == [("a",), ("b", "c")]


@pytest.mark.parametrize(
    ("source", "kind"),
    [
        ("x = 1", "integer"),
        ("x = 1.5", "float"),
        ("x = true", "bool"),
        ('x = "t"', "string"),
        ("x = 2024-01-01", "date"),
        ("x = 12:00:00", "time"),
        ("x = 2024-01-01T12:00:00", "datetime"),
    ],
)
def test_reads_what_kind_a_scalar_is(source, kind):
    (entry,) = parse(f"{source}\n").root
    assert isinstance(entry.value, Scalar)
    assert entry.value.kind == kind


def test_a_string_keeps_both_its_spelling_and_its_text():
    (entry,) = parse(r'x = "a\tb"' + "\n").root
    assert isinstance(entry.value, Scalar)
    assert entry.value.raw == r'"a\tb"'
    assert entry.value.text == "a\tb"


def test_replacing_a_string_drops_the_old_spelling():
    (entry,) = parse('x = "a"\n').root
    assert isinstance(entry.value, Scalar)
    entry.value.replace_text("b")
    assert entry.value.raw is None
    assert entry.value.text == "b"


def test_every_entry_carries_the_table_it_sits_in():
    document = parse("a = 1\n[t]\nb = 2\n[[u]]\nc = 3\n")
    assert list(document.entries()) == [
        ((), document.root[0]),
        (("t",), document.sections[0].entries[0]),
        (("u",), document.sections[1].entries[0]),
    ]
