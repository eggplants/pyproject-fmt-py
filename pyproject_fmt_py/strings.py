"""Choosing the form a string or a key name is written in.

A value that would gain a quote is better off literal, and one the file already spelled at no more
length than the plainest form is left as it was. Keys read a grammar of their own: a name TOML
takes bare is written bare, whatever the file did.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .document import Scalar

#: What a key may be written as without quotes.
_BARE = re.compile(r"[A-Za-z0-9_-]+")

_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


def fits_literal(text: str) -> bool:
    """Whether the text can sit inside a literal string, which has no escapes of its own."""
    return "'" not in text and not any(_is_control(character) and character != "\t" for character in text)


def encode_basic(text: str) -> str:
    """Write the text as a basic string, quotes included, escaping what TOML requires."""
    out = ['"']
    for character in text:
        if character in _ESCAPES:
            out.append(_ESCAPES[character])
        elif _is_control(character):
            out.append(f"\\u{ord(character):04X}")
        else:
            out.append(character)
    out.append('"')
    return "".join(out)


def encode_literal(text: str) -> str:
    """Write the text as a literal string, or as a basic one where it cannot hold it."""
    return f"'{text}'" if fits_literal(text) else encode_basic(text)


def encode_key_segment(name: str) -> str:
    """Write one key segment: bare where TOML reads one bare, and quoted where it does not."""
    if name and _BARE.fullmatch(name):
        return name
    # the name is spelled as a string would be, so a name holding a quote stays out of escapes
    return encode_literal(name) if '"' in name else encode_basic(name)


def plainest_form(text: str) -> str | None:
    """The plainest single-line spelling of the text, or None where the file's own is no worse.

    A value holding a double quote is written literal, which saves it the escapes. One holding a
    backslash is left alone: writing it basic would only add escapes the file did without.
    """
    if '"' in text:
        return f"'{text}'" if fits_literal(text) else None
    if "\\" in text:
        return None
    return encode_basic(text)


def normalize_quotes(scalar: Scalar) -> str:
    """The text a scalar is written as, in the plainest form that still says the same thing."""
    if scalar.kind != "string":
        return scalar.raw or ""
    if scalar.raw is not None and _is_multiline(scalar.raw):
        return scalar.raw  # a value keeping its newlines stays the multi-line string it was
    plainest = plainest_form(scalar.text)
    if plainest is not None:
        return plainest
    return scalar.raw if scalar.raw is not None else encode_basic(scalar.text)


def _is_multiline(written: str) -> bool:
    return written.startswith(('"""', "'''"))


def _is_control(character: str) -> bool:
    return character < " " or character == "\x7f"
