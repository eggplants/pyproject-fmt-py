"""Reading and writing the names TOML gives its keys.

A name is a tuple of segments, so `a."b.c"` (two segments) and `a.b.c` (three) stay apart wherever
one table is selected from another.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import tomlkit
from tomlkit.exceptions import TOMLKitError
from tomlkit.items import Item, Key, Table, Whitespace

from .strings import encode_basic, encode_key_segment

if TYPE_CHECKING:
    from collections.abc import Iterable

KeyPath = tuple[str, ...]


def parse_key_path(name: str) -> KeyPath:
    """Read a key path the way TOML reads one.

    Args:
        name: The text of the path, such as `tool."a.b".c`.

    Returns:
        One segment per key the path names.

    Raises:
        ValueError: If the text is not a key path, with why.
    """
    try:
        document = tomlkit.parse(f"{name} = 0\n")
    except TOMLKitError as exc:
        msg = str(exc)
        raise ValueError(msg) from exc
    items = _named(document.body)
    if len(items) != 1:
        msg = "it says more than a name"
        raise ValueError(msg)
    key, value = items[0]
    segments: list[str] = []
    while True:
        segments.append(key.key)
        if not (key.is_dotted() and isinstance(value, Table)):
            return tuple(segments)
        key, value = _named(value.value.body)[0]


def _named(body: Iterable[tuple[Key | None, Item]]) -> list[tuple[Key, Item]]:
    """The entries of a container that carry a key, dropping the whitespace between them."""
    return [(key, value) for key, value in body if key is not None and not isinstance(value, Whitespace)]


def render_key(segments: Iterable[str]) -> str:
    """Write a key path out, quoting only the segments that need it."""
    return ".".join(render_segment(segment) for segment in segments)


def render_segment(segment: str) -> str:
    """Write one segment, bare where TOML allows it and quoted otherwise."""
    return encode_key_segment(segment)


def dotted_name(segments: Iterable[str]) -> str:
    """The segments as the one dotted name a rule is written against.

    A segment TOML cannot read bare is quoted, so the name reads back as the segments it was built
    from. This is what a table is looked up by, which is why it never picks the literal form a
    value would take: a rule spells a name one way only.
    """
    return ".".join(segment if _is_bare(segment) else encode_basic(segment) for segment in segments)


def _is_bare(segment: str) -> bool:
    return bool(segment) and encode_key_segment(segment) == segment


def is_under(name: KeyPath, prefix: KeyPath) -> bool:
    """Whether `name` is `prefix` or sits below it, compared segment by segment."""
    return len(name) >= len(prefix) and name[: len(prefix)] == prefix
