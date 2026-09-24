"""What a table asks of the formatter, in one place.

A table's name, its key order and how its values are read all say something about the same table,
so they are written together rather than in three lists that have to agree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


def nothing(_key: str) -> bool:
    """Whether a name holds nothing this reads, which is what a table without such values says."""
    return False


@dataclass(frozen=True)
class TableRule:
    """A table the formatter reads by its key order alone.

    Attributes:
        table: The table these rules format, spelled as the file spells its path.
        order: Where each key sits among the others.
        sorts: Whether what the name holds is a list of names, which sorts.
        dedupes: Whether that list also says each name once.
        keeps_order: The keys the file's own sequence orders, since where each one sits says
            something the formatter cannot second-guess.
    """

    table: str
    order: tuple[str, ...] = ()
    sorts: Callable[[str], bool] = nothing
    dedupes: Callable[[str], bool] = nothing
    keeps_order: tuple[str, ...] = field(default=())


def among(*names: str) -> Callable[[str], bool]:
    """A predicate for the names spelled out here."""
    held = frozenset(names)
    return held.__contains__


def leaf_among(*names: str) -> Callable[[str], bool]:
    """A predicate reading only the last segment, since a list is a list wherever it is written."""
    held = frozenset(names)

    def holds(key: str) -> bool:
        return key.rsplit(".", 1)[-1] in held

    return holds


def either(*predicates: Callable[[str], bool]) -> Callable[[str], bool]:
    """A predicate that holds where any of the ones given does."""

    def holds(key: str) -> bool:
        return any(predicate(key) for predicate in predicates)

    return holds


def under(*prefixes: str) -> Callable[[str], bool]:
    """A predicate for the names written below one of these, which never names the prefix itself."""

    def holds(key: str) -> bool:
        return any(key.startswith(prefix) and len(key) > len(prefix) for prefix in prefixes)

    return holds
