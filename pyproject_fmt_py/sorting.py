"""The order almost every list in a formatted file reads in.

What a name says rather than how it is written: a number by its value so `py9` leads `py10`, an
accent beside the letter it sits on so `é` falls between `e` and `f`, and punctuation before both.
Where two names say the same thing, the one the file wrote first stays first.

The accent handling is Unicode decomposition rather than a collation table, so a letter no
decomposition reaches, such as `æ`, sorts by its own code point instead of by the letters it
stands for.
"""

from __future__ import annotations

import re
import unicodedata

#: Letters that carry no decomposition of their own, spelled as the letters they stand for.
_STANDS_FOR = {
    "æ": "ae",
    "œ": "oe",
    "ø": "o",
    "ð": "d",
    "đ": "d",
    "ł": "l",
    "þ": "th",
    "\u0131": "i",
}

#: A run of digits, or one character that is not one.
_PIECE = re.compile(r"\d+|\D")

#: What a piece sorts under: punctuation, then digits, then letters.
_PUNCTUATION, _DIGITS, _LETTERS = 0, 1, 2

Token = tuple[int, int, int, str]


def natural_lexical_key(text: str) -> tuple[list[Token], str]:
    """The key a list of names sorts by.

    Callers that ignore case lower the text before handing it over, which is what leaves the
    spelling to decide only where two names say the same thing.
    """
    return _pieces(_folded(text)), text


def _folded(text: str) -> str:
    """The text with its case and its accents taken off, so only what it says is left."""
    out: list[str] = []
    for character in unicodedata.normalize("NFKD", text.casefold()):
        if unicodedata.combining(character):
            continue
        out.append(_STANDS_FOR.get(character, character))
    return "".join(out)


def _pieces(text: str) -> list[Token]:
    """The text as the things it is written out of: digit runs by value, everything else by kind.

    A run of digits carries how many it was written with, so `1` leads `01`, which says the same
    number at more length.
    """
    tokens: list[Token] = []
    for piece in _PIECE.findall(text):
        if piece[0].isdigit():
            tokens.append((_DIGITS, int(piece), len(piece), ""))
        else:
            tokens.append((_LETTERS if piece.isalpha() else _PUNCTUATION, 0, 0, piece))
    return tokens
