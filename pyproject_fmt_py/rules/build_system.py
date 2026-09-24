"""The PEP 517/518 table that declares how the project is built."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..arrays import map_strings, sort_strings
from ..document import Array
from ..pep508 import Requirement
from ..sections import for_keys_under, reorder_under
from ..sorting import natural_lexical_key

if TYPE_CHECKING:
    from ..document import Document, Value

#: `backend-path` keeps its input order, which controls the frontend's search.
KEY_ORDER: tuple[str, ...] = ("build-backend", "requires", "backend-path")

PATH = ("build-system",)


def fix(document: Document, *, keep_full_version: bool) -> None:
    """Normalize the requirements the table declares, then put its keys in order."""

    def visit(key: str, value: Value) -> None:
        if key != "requires":
            return
        map_strings(value, lambda text: normalized(text, keep_full_version=keep_full_version))
        if isinstance(value, Array):
            sort_strings(value, lambda text: natural_lexical_key(sort_name(text)))

    for_keys_under(document, PATH, visit)
    reorder_under(document, PATH, KEY_ORDER)


def normalized(text: str, *, keep_full_version: bool) -> str:
    """The requirement in its canonical spelling, or as the file wrote it where it reads as none."""
    try:
        return str(Requirement.parse(text).normalize(keep_full_version=keep_full_version))
    except ValueError:
        return text


def sort_name(text: str) -> str:
    """The name a requirement installs, which is what a list of them sorts by."""
    try:
        return Requirement.parse(text).canonical_name
    except ValueError:
        return text
