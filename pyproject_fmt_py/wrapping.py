"""Breaking a string that outgrows the column across lines with `\\` continuations.

A wrapped value is still one unbroken string: every line it is written over ends in a continuation,
which eats the line break and the whitespace after it. A value whose own whitespace would go with
them is left as the file wrote it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import tomlkit
from tomlkit.exceptions import TOMLKitError

from .document import Array, InlineTable, Scalar
from .keys import KeyPath, parse_key_path, render_key
from .strings import encode_basic
from .width import break_points, columns

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from .document import Document, Entry, Value

#: What `"""\` takes, which is what a wrapped value opens its first line with.
OPENER = 4

#: What separates the parts of a classifier, which a line breaks after by preference.
CLASSIFIER_SEPARATOR = " :: "

#: What one component of a pattern names: `None` for any one segment, or the name it spells.
Want = str | None
Pattern = tuple[Want, ...]


@dataclass(frozen=True)
class Wrap:
    """Where a value sits, which decides whether it may be wrapped and how far it is pushed in.

    Attributes:
        column_width: How wide a line may run.
        indent: What a continuation line opens with.
        prefix: What the layout writes on the line before the value: the key and its `= `, or the
            indent a nested value is pushed in by.
        inline_table: Whether the value sits inside `{ }`, which cannot break across lines.
    """

    column_width: int
    indent: str
    prefix: int
    inline_table: bool = False


def wrap_long_strings(document: Document, column_width: int, indent: int, skip: Sequence[str] = ()) -> None:
    """Wrap every string that outgrows the column, apart from the keys `skip` names.

    Args:
        document: The document to wrap in place.
        column_width: How wide a line may run.
        indent: How far a continuation is pushed in.
        skip: Key patterns whose values carry meaning that line breaks would obscure.
    """
    padding = " " * indent
    patterns = [read_pattern(text) for text in skip]
    for table, entry in document.entries():
        _wrap_entry(entry, table, column_width, padding, patterns)


def _wrap_entry(entry: Entry, table: KeyPath, column_width: int, indent: str, patterns: Sequence[Pattern]) -> None:
    # a pattern is written against the key's whole path, table included, so `*.skip_me` reaches a
    # key of that name under any table
    path = (*table, *entry.key)
    if any(matches_key(path, pattern) for pattern in patterns):
        return
    # the layout writes `key = ` ahead of the value, which is part of what the line runs to; the
    # key is measured as the layout will write it, not as the file spaced it out
    prefix = columns(render_key(entry.key)) + len(" = ")
    _wrap_value(entry.value, Wrap(column_width=column_width, indent=indent, prefix=prefix), depth=0)


def _wrap_value(value: Value, wrap: Wrap, depth: int) -> None:
    if isinstance(value, Scalar):
        _wrap_scalar(value, wrap)
    elif isinstance(value, Array):
        # a member of an array the layout opens starts its line one level further in
        inside = len(wrap.indent) * (depth + 1)
        for member in value.members:
            _wrap_value(member.value, Wrap(wrap.column_width, wrap.indent, inside, wrap.inline_table), depth + 1)
    elif isinstance(value, InlineTable):
        for entry in value.entries:
            _wrap_value(entry.value, Wrap(wrap.column_width, wrap.indent, wrap.prefix, inline_table=True), depth)


def _wrap_scalar(scalar: Scalar, wrap: Wrap) -> None:
    if scalar.kind != "string" or wrap.inline_table:
        return
    text = scalar.text
    if "\n" in text:
        return  # a string the file already spread over lines is left as it wrote it
    # a value the key ahead of it pushes past the column is broken up, as long as what opens a
    # multi-line string still fits after that key: a key already over the column on its own cannot
    # be brought back by rewriting its value
    if wrap.prefix + columns(encode_basic(text)) <= wrap.column_width:
        return
    if wrap.prefix + OPENER > wrap.column_width:
        return
    broken = wrap_with_continuations(text, wrap.column_width, wrap.indent)
    if broken is not None and _reads_back_as(broken, text):
        scalar.raw = broken


def wrap_with_continuations(text: str, column_width: int, indent: str) -> str | None:
    """Break the text across lines so the written form fits the column.

    Returns:
        The multi-line string the text is written as, or None where the column has no room for
        that form: a width that cannot hold the indent, one character and the continuation after
        it would only trade a long line for a longer one.
    """
    escaped = encode_basic(text)[1:-1]
    # the continuation the line ends with takes a column of its own
    effective_width = column_width - (len(indent) + 1)
    if effective_width < 0:
        return None
    written = ['"""\\\n']
    start = 0
    while start < len(escaped):
        remaining = escaped[start:]
        if columns(remaining) + len(indent) < column_width:
            written.append(f"{indent}{remaining}\\\n")
            break
        split_at = _wrap_point(remaining, effective_width)
        written.append(f"{indent}{remaining[:split_at]}\\\n")
        start += split_at
    written.append(f'{indent}"""')
    result = "".join(written)
    # a character wider than what is left of the line has to go somewhere, and a line it runs past
    # the column is not the wrapping the caller asked for
    if all(columns(line) <= column_width for line in result.split("\n")[1:]):
        return result
    return None


def _wrap_point(text: str, max_len: int) -> int:
    """Break after a classifier separator, else after the last space, else where the width runs out."""
    ends = break_points(text, max_len)
    if not ends:
        return len(text)
    head_end = next((end for end in reversed(ends) if columns(text[:end]) <= max_len), ends[0])
    head = text[:head_end]
    position = head.rfind(CLASSIFIER_SEPARATOR)
    if position != -1:
        return position + len(CLASSIFIER_SEPARATOR)
    position = head.rfind(" ")
    return position + 1 if position != -1 else head_end


def _reads_back_as(written: str, text: str) -> bool:
    try:
        return str(tomlkit.parse(f"x = {written}\n")["x"]) == text
    except TOMLKitError:  # pragma: no cover - the wrapper writes a string a reader accepts
        return False


def read_pattern(text: str) -> Pattern:
    """The segments a pattern names, read the way TOML reads a key.

    A dot inside quotes belongs to the segment around it, so `tool."a.b".commands` names three
    segments rather than four. `*` stands for a segment of its own and is never a name, since TOML
    has no bare key spelled that way.
    """
    return tuple(_one_segment(component) for component in _split_outside_quotes(text))


def matches_key(path: KeyPath, pattern: Pattern) -> bool:
    """Whether the key path is the one the pattern names.

    A pattern matches segment by segment, with `*` standing for any one segment. A pattern opening
    with `*` matches the tail of the path, so `*.commands` reaches `commands` under any table; one
    ending in `*` matches from the head, so `tool.ruff.*` covers what is written under that table.
    """
    if len(pattern) > len(path):
        return False
    leads, ends = pattern[0] is None, pattern[-1] is None
    if not leads and not ends and len(pattern) != len(path):
        return False
    start = len(path) - len(pattern) if leads and len(pattern) > 1 else 0
    return all(want is None or want == have for want, have in zip(pattern, path[start:], strict=False))


def _split_outside_quotes(text: str) -> Iterable[str]:
    components: list[str] = []
    start = 0
    quote: str | None = None
    escaped = False
    for at, held in enumerate(text):
        if quote == '"' and held == "\\":
            escaped = not escaped
        elif quote is not None and held == quote and not escaped:
            quote = None
        elif quote is not None:
            escaped = False
        elif held in "\"'":
            quote = held
        elif held == ".":
            components.append(text[start:at])
            start = at + 1
    components.append(text[start:])
    return components


def _one_segment(component: str) -> Want:
    """What one component names, with its quoting resolved.

    A bare `*` stands for any one segment, while a quoted one names the key spelled that way. A
    component TOML cannot read as a key names itself.
    """
    if component == "*":
        return None
    try:
        segments = parse_key_path(component)
    except ValueError:
        return component
    return segments[0] if len(segments) == 1 else component
