"""How many empty lines sit between one table and the next.

Sections belonging to the same tool are held together; a change of tool gets a wider gap. The gap
goes above a section's leading comments, which belong to the section rather than to what came
before it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .document import Array, InlineTable, Scalar

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .document import Document, Value
    from .keys import KeyPath

#: Tables whose children group one level deeper, so `tool.ruff` and `tool.mypy` are told apart.
NESTED_PREFIXES: tuple[str, ...] = ("tool",)

#: How long a run of empty lines may be anywhere in the document.
BLANK_RUN_LIMIT = 2


def apply(
    document: Document,
    *,
    between_groups: int,
    within_group: int | None,
    nested_prefixes: Sequence[str] = NESTED_PREFIXES,
) -> None:
    """Set the gap above every table but the first, then cap every run of empty lines.

    Args:
        document: The document to space out, changed in place.
        between_groups: Empty lines between tables of different tools.
        within_group: Empty lines between tables of the same tool, or None to leave them as the
            file wrote them.
        nested_prefixes: Table names whose children group one level deeper.
    """
    # nothing precedes the first line, so a gap above it would be a gap above nothing
    opening = document.root[0].lead if document.root else document.sections[0].lead if document.sections else None
    if opening is not None:
        _set_gap(opening, 0)

    groups = [_base(section.name, nested_prefixes) for section in document.sections]
    if document.root and document.sections:
        _set_gap(document.sections[0].lead, between_groups)
    for index in range(1, len(document.sections)):
        section, before = document.sections[index], document.sections[index - 1]
        if section.name == before.name:
            continue  # repeated `[[table]]` entries carry their own spacing
        if groups[index] == groups[index - 1]:
            if within_group is None:
                continue
            _set_gap(section.lead, within_group)
        else:
            _set_gap(section.lead, between_groups)

    limit_blank_runs(document)


def limit_blank_runs(document: Document, most: int = BLANK_RUN_LIMIT) -> None:
    """Cap every run of empty lines at `most`, wherever the document holds one.

    This walks the document's own trivia rather than its text, which is what keeps the empty lines
    inside a multi-line string out of reach.
    """
    for entry in document.root:
        entry.lead[:] = _capped(entry.lead, most)
        _limit_within(entry.value, most)
    for section in document.sections:
        section.lead[:] = _capped(section.lead, most)
        for entry in section.entries:
            entry.lead[:] = _capped(entry.lead, most)
            _limit_within(entry.value, most)
    document.trailing[:] = _capped(document.trailing, most)


def _limit_within(value: Value, most: int) -> None:
    if isinstance(value, Scalar):
        return  # a scalar's own text is what the value says, so the walk stops there
    if isinstance(value, Array):
        for member in value.members:
            member.lead[:] = _capped(member.lead, most)
            _limit_within(member.value, most)
        value.trailing[:] = _capped(value.trailing, most)
    elif isinstance(value, InlineTable):
        for entry in value.entries:
            _limit_within(entry.value, most)


def _set_gap(lead: list[str], blanks: int) -> None:
    """Replace whatever empty lines a lead opens with by exactly `blanks` of them."""
    opening = next((index for index, piece in enumerate(lead) if piece), len(lead))
    lead[:opening] = [""] * blanks


def _capped(lead: Sequence[str], most: int) -> list[str]:
    out: list[str] = []
    run = 0
    for piece in lead:
        run = run + 1 if not piece else 0
        if run <= most:
            out.append(piece)
    return out


def _base(name: KeyPath, nested_prefixes: Sequence[str]) -> KeyPath:
    """The name a table groups under: one level deeper for the nested prefixes.

    The answer is the segments themselves, not the name they join into: joining first would make
    `tool."a.b"` and `tool.a.b` the same table.
    """
    width = 2 if name and name[0] in nested_prefixes else 1
    return name[: min(width, len(name))]
