"""How wide a piece of text is written.

`column_width` names columns rather than bytes, so a CJK character takes two of them and a
combining mark none.
"""

from __future__ import annotations

import unicodedata

from wcwidth import wcswidth


def columns(text: str) -> int:
    """How many columns the text takes to write.

    Text holding something with no width of its own, such as a control character, falls back to
    one column per character rather than claiming to know better.
    """
    width = wcswidth(text)
    return width if width >= 0 else len(text)


def last_line_columns(text: str) -> int:
    """How wide the line the text ends on is, which is what moves whatever follows it."""
    return columns(text.rsplit("\n", 1)[-1])


def break_points(text: str, max_columns: int) -> list[int]:
    """The offsets a line may end at, up to the first one past `max_columns`.

    A character and a TOML escape each stand for one thing the file says, so breaking inside
    either would write something the file does not.
    """
    points: list[int] = []
    at = width = 0
    while at < len(text):
        held = _held_at(text, at)
        at = min(at + held, len(text))
        width += max(columns(text[at - held : at]), 1)
        points.append(at)
        if width > max_columns:
            break
    return points


def _held_at(text: str, at: int) -> int:
    """How many characters the one thing written at `at` takes."""
    if text[at] == "\\":  # the body was escaped, whose longest escape is `\uXXXX`
        return 6 if text[at + 1 : at + 2] == "u" else 2
    length = 1
    while at + length < len(text) and unicodedata.combining(text[at + length]):
        length += 1
    return length
