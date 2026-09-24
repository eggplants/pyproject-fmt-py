"""The PEP 735 table of dependency groups."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..arrays import map_strings, sort_runs, text_of
from ..document import Array, InlineTable
from ..nesting import Width, collapse
from ..sections import for_keys_under, reorder_under
from ..sorting import natural_lexical_key
from .build_system import normalized, sort_name

if TYPE_CHECKING:
    from ..document import Document, Member, Value

#: The groups a project writes first, where it writes them.
KEY_ORDER: tuple[str, ...] = ("dev", "test", "type", "docs")

PATH = ("dependency-groups",)


def fix(document: Document, *, keep_full_version: bool) -> None:
    """Normalize every requirement a group names, and sort what is free to move."""
    collapse(document, PATH, lambda _name: True, Width.unbounded())

    def visit(_key: str, value: Value) -> None:
        if not isinstance(value, Array):
            return
        map_strings(value, lambda text: normalized(text, keep_full_version=keep_full_version))
        # an `include-group` puts the group it names where it is written, so it stays there and
        # only the requirements written between two of them sort
        sort_runs(value, _includes_a_group, _sorts_by)

    for_keys_under(document, PATH, visit)
    reorder_under(document, PATH, KEY_ORDER)


def _includes_a_group(member: Member) -> bool:
    return isinstance(member.value, InlineTable)


def _sorts_by(member: Member) -> tuple[object, object] | None:
    """The name the requirement installs leads, and the whole line settles a tie."""
    text = text_of(member)
    if text is None:
        return None
    return natural_lexical_key(sort_name(text)), natural_lexical_key(text)
