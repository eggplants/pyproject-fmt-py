"""A comment whose body is one key-value is a disabled field rather than prose.

`# default = true` is a field the author turned off, so the pass uncomments it, lets the formatter
sort it with its table, and comments it back. Without that it would drift to the next table and
never get ordered.

A value can span several comment lines: `# x = [` alone is invalid, yet `# x = [` / `#   1,` /
`# ]` parses once the run is uncommented together, so enabling works on whole runs.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import tomlkit
from tomlkit import items as tk
from tomlkit.exceptions import TOMLKitError

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from .document import Entry

#: Tags a disabled key's trailing comment so the pass can find it again after the formatter has
#: reordered and re-parsed everything. A file is free to hold this text itself, so the marker a
#: pass uses is built from this one and is not one the source already writes.
MARKER = "__toml_fmt_disabled__"

#: The marker of the pass that is running, or None outside one.
_in_use: list[str | None] = [None]


@contextlib.contextmanager
def in_use(marker: str) -> Iterator[None]:
    """Hold the marker for as long as the pass runs, and take it back however the pass ends."""
    _in_use[0] = marker
    try:
        yield
    finally:
        _in_use[0] = None


def is_enabled_here(entry: Entry) -> bool:
    """Whether the entry is one this pass turned back on, which the marker beside it says.

    A pass that would split, drop or merge such an entry has to leave it alone: what says the entry
    is disabled is the comment beside it, and none of those rewrites can say it of what they leave.
    """
    marker = _in_use[0]
    if marker is None or entry.comment is None:
        return False
    body = entry.comment.lstrip("#").strip()
    return body == marker or body.rsplit(maxsplit=1)[-1:] == [kept_marker(marker)]


def kept_marker(marker: str) -> str:
    """The marker as it is written inside a comment the file wrote, which stays where it is."""
    return f"{marker}-kept"


def fresh_marker(source: str) -> str:
    """A marker the source does not already hold, so nothing the file says reads as one.

    Every marker this can pick is the base one followed by some number of `x`, so the longest run
    the file already writes after it says how many the marker needs to be one of its own.
    """
    longest = -1
    at = source.find(MARKER)
    while at != -1:
        rest = source[at + len(MARKER) :]
        longest = max(longest, len(rest) - len(rest.lstrip("x")))
        at = source.find(MARKER, at + 1)
    return MARKER + "x" * (longest + 1)


def enable(source: str, marker: str) -> str | None:
    """The source with its disabled keys turned back on, or None where it holds none."""
    standing = standing_comment_lines(source)
    lines = source.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    out: list[str] = []
    turned_on = False
    at = 0
    while at < len(lines):
        split = _split_comment(lines[at]) if at in standing else None
        if split is None:
            out.append(lines[at])
            at += 1
            continue
        indent, body = split
        if _is_a_table_header(body):
            # the keys under a commented header would otherwise leave the table they belong to
            out.append(lines[at])
            at += 1
            while at < len(lines) and _split_comment(lines[at]) is not None:
                out.append(lines[at])
                at += 1
            continue
        held = _enable_block(lines, at, marker)
        if held is None:
            out.append(lines[at])
            at += 1
            continue
        end, enabled = held
        out.append(f"{indent}{enabled}")
        turned_on = True
        at = end + 1
    return _joined_like(source, out) if turned_on else None


def restore(formatted: str, spans: Sequence[tuple[int, int]], marker: str) -> str:
    """Comment the lines of every entry the pass enabled back out."""
    lines = formatted.split("\n")
    trailing = lines and lines[-1] == ""
    if trailing:
        lines.pop()
    plan: list[tuple[int, bool] | None] = [None] * len(lines)
    for start, end in spans:
        if start >= len(lines):
            continue
        first = lines[start]
        indent = len(first) - len(first.lstrip())
        for at in range(start, min(end, len(lines) - 1) + 1):
            plan[at] = (indent, at == end)
    restored = [
        line if held is None else _commented(line, held[0], marker if held[1] else None)
        for line, held in zip(lines, plan, strict=True)
    ]
    return _joined_like(formatted, restored)


def standing_comment_lines(source: str) -> set[int]:
    """The lines the file wrote a comment on where a key could have stood.

    A `#` anywhere else is part of what a value says: inside a multi-line string or inside an
    array, no key can stand there and uncommenting one would rewrite the value.
    """
    standing: set[int] = set()
    inside: str | None = None
    depth = 0
    for at, line in enumerate(source.split("\n")):
        if inside is None and depth == 0 and line.lstrip().startswith("#"):
            standing.add(at)
            continue
        inside, depth = _read_line(line, inside, depth)
    return standing


def _read_line(line: str, inside: str | None, depth: int) -> tuple[str | None, int]:
    """How much of a value is still open once this line has been read."""
    rest = line
    while rest:
        if inside is not None:
            if rest.startswith(inside):
                rest, inside = rest[len(inside) :], None
                continue
            # only a basic string reads a backslash as opening an escape
            rest = rest[2:] if inside.startswith('"') and rest.startswith("\\") else rest[1:]
            continue
        opening = next((held for held in ('"""', "'''", '"', "'") if rest.startswith(held)), None)
        if opening is not None:
            rest, inside = rest[len(opening) :], opening
            continue
        held = rest[0]
        if held in "[{":
            depth += 1
        elif held in "]}":
            depth = max(depth - 1, 0)
        elif held == "#":  # a comment runs to the end of its line
            break
        rest = rest[1:]
    # a string written with one quote closes on the line it opened
    return (None if inside is not None and len(inside) == 1 else inside), depth


def _enable_block(lines: Sequence[str], start: int, marker: str) -> tuple[int, str] | None:
    """The run from `start` until the value it opens closes, uncommented and marked."""
    inside: str | None = None
    depth = 0
    bodies: list[str] = []
    for end in range(start, len(lines)):
        split = _split_comment(lines[end])
        if split is None:
            return None
        bodies.append(split[1])
        inside, depth = _read_line(split[1], inside, depth)
        if inside is None and depth == 0:
            enabled = _enabled_form("\n".join(bodies), marker)
            return (end, enabled) if enabled is not None else None
    return None


def _enabled_form(body: str, marker: str) -> str | None:
    """`body` with the marker added, or None unless it is exactly one key-value.

    A key-value is written above the body being read, which puts it where the file wrote it: inside
    a document rather than at the start of one. The marker extends a comment already on the last
    line, so the value never ends up with two trailing comments.
    """
    try:
        parsed = tomlkit.parse(f"{marker} = 0\n{body}\n")
    except TOMLKitError:
        return None
    items = [(key, value) for key, value in parsed.body if not isinstance(value, tk.Whitespace)]
    if len(items) != 2 or any(key is None for key, _ in items):  # noqa: PLR2004 - the key ahead, then the body
        return None
    key, value = items[1]
    if _opens_a_table(key, value):
        return None
    # the marker says which comment it is written in, since only the one it opened comes off again
    if value.trivia.comment:
        return f"{body} {kept_marker(marker)}"
    return f"{body}  # {marker}"


def _is_a_table_header(body: str) -> bool:
    try:
        parsed = tomlkit.parse(body)
    except TOMLKitError:
        return False
    return any(_opens_a_table(key, value) for key, value in parsed.body)


def _opens_a_table(key: tk.Key | None, value: tk.Item) -> bool:
    """Whether the item is a `[name]` header rather than the dotted key that reads the same way."""
    if isinstance(value, tk.AoT):
        return True
    return isinstance(value, tk.Table) and not (key is not None and key.is_dotted())


def _split_comment(line: str) -> tuple[str, str] | None:
    """The indent and the body of a comment line, dropping one space after `#`."""
    trimmed = line.lstrip()
    if not trimmed.startswith("#"):
        return None
    rest = trimmed[1:]
    return line[: len(line) - len(trimmed)], rest.removeprefix(" ")


def _commented(line: str, base: int, marker: str | None) -> str:
    """Write the line back out as a comment, with the `#` at the key's own column."""
    cleaned = _without_marker(line, marker) if marker is not None else line
    cut = min(base, len(cleaned))
    return f"{cleaned[:cut]}# {cleaned[cut:]}"


def _without_marker(line: str, marker: str) -> str:
    """The line without the marker, and without the comment the marker opened."""
    kept = kept_marker(marker)
    at = line.rfind(kept)
    if at != -1:
        return line[:at].rstrip()
    at = line.rfind(marker)
    if at == -1:  # pragma: no cover - the line a span ends on carries the marker
        return line
    before = line[:at].rstrip()
    return before[:-1].rstrip() if before.endswith("#") else before


def _joined_like(original: str, lines: Sequence[str]) -> str:
    joined = "\n".join(lines)
    return f"{joined}\n" if original.endswith("\n") else joined
