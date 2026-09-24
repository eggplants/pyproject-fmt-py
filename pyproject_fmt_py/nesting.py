"""Moving entries between a table and the sub-tables written under it.

`[tool.x] a.b = 1` and `[tool.x.a] b = 1` describe the same document, so a formatter can pick
either. Collapsing folds a sub-table into its parent as dotted keys; expanding writes the dotted
keys back out as their own header.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias

from .disabled import is_enabled_here
from .document import Array, Entry, InlineTable, Member, Section
from .render import fits_one_line

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .document import Document

from .keys import KeyPath

#: Whether a table is one the caller is asking about, read from the name it was given.
Wanted: TypeAlias = Callable[[KeyPath], bool]


@dataclass(frozen=True)
class Width:
    """How wide a line may run and how far a nested one is pushed in, which a folded table has to fit."""

    column: int
    indent: int

    @classmethod
    def unbounded(cls) -> Width:
        """A width nothing outgrows, for a fold whose shape is not in question."""
        return cls(column=2**31, indent=2)


def collapse(document: Document, root: KeyPath, wanted: Wanted, width: Width) -> None:
    """Fold `[root.sub]` into `[root]` as `sub.key` entries, and `[[root.sub]]` into `sub = [ … ]`.

    A repeated header, or a sub-table that still has tables of its own beneath it, stays where it
    is: neither survives the move.
    """
    # fold the deepest table first, so `[a.b.c]` reaches `[a]` as `b.c.key` however many levels
    # were written out and whichever of them the file skipped
    left_alone: list[KeyPath] = []
    pending = _deepest_first(document, root, left_alone)
    while pending:
        sub = pending.pop()
        # the parent is this table minus its last segment, taken from the segments themselves so a
        # name holding a dot is not cut in half
        parent = sub[:-1]
        if _is_array_of_tables(document, sub):
            if wanted(sub):
                collapse_array_of_tables(document, sub, width)
            left_alone.append(sub)
            continue
        if not _folds_in(document, sub, wanted):
            left_alone.append(sub)
            continue
        held = len(document.sections)
        _ensure_exists(document, parent)
        # writing the parent out puts a table under `root` that was not there to read before
        if len(document.sections) > held:
            pending = [name for name in _deepest_first(document, root, left_alone) if name != sub]
        _fold_into_parent(document, sub)


def _fold_into_parent(document: Document, sub: KeyPath) -> None:
    """Take `[sub]` out and write what it held under its parent as `leaf.key` entries."""
    at = _index_of(document, sub)
    parent = sub[:-1]
    if at is None:  # pragma: no cover - the table was there a moment ago
        return
    section = document.sections.pop(at)
    parent_at = _index_of(document, parent)
    if parent_at is None:  # pragma: no cover - the parent was just written out
        return
    leaf = sub[len(parent) :]
    if not section.entries:
        document.sections[parent_at].entries.append(_empty_table_entry(leaf, section))
        return
    for entry in section.entries:
        entry.key = (*leaf, *entry.key)
    # the comments above and beside the header now lead the first key it brought along; the blank
    # lines set the header apart from the table above it, and that gap is gone
    kept = [piece for piece in section.lead if piece]
    if section.comment:
        kept.append(section.comment)
    section.entries[0].lead[:0] = kept
    document.sections[parent_at].entries.extend(section.entries)


def _folds_in(document: Document, sub: KeyPath, wanted: Wanted) -> bool:
    """Whether the table can be folded into its parent, and is one the caller asked to fold."""
    # a parent written more than once has no one place to fold into: the keys belong to the element
    # the file wrote them under
    if not _movable(document, sub) or not _can_hold(document, sub[:-1]) or not wanted(sub):
        return False
    at = _index_of(document, sub)
    if at is None:  # pragma: no cover - the name came out of the document
        return False
    entries = document.sections[at].entries
    # a table with nothing in it still holds whatever was written under it, and folding it into
    # `leaf = {}` would leave those tables with no table of their own to belong to
    if not entries:
        return not _has_tables_below(document, sub)
    # a table whose every key is disabled is one the file wrote empty, and folding those keys into
    # the parent as comments would leave nothing saying the table is there at all
    return not all(is_enabled_here(entry) for entry in entries)


def expand(document: Document, name: KeyPath, wanted: Wanted) -> None:
    """Write the dotted keys of `[name]` back out as `[name.sub]` headers."""
    parent = _index_of(document, name)
    if parent is None:
        return
    moved: list[tuple[KeyPath, list[Entry]]] = []
    kept: list[Entry] = []
    for entry in document.sections[parent].entries:
        # a disabled key is one the comment beside it speaks for, and a header written for it would
        # carry none of that
        head = None if is_enabled_here(entry) else _leading_segments(entry, name, wanted)
        if head is None:
            kept.append(entry)
            continue
        entry.key = entry.key[len(head) :]
        for existing, bucket in moved:
            if existing == head:
                bucket.append(entry)
                break
        else:
            moved.append((head, [entry]))
    document.sections[parent].entries = kept

    at = parent + 1
    for head, entries in moved:
        document.sections.insert(at, Section(name=(*name, *head), kind="table", entries=entries))
        at += 1


def collapse_array_of_tables(document: Document, name: KeyPath, width: Width) -> None:
    """Fold every `[[name]]` back into its parent as `field = [ { … } ]`."""
    field, parent = name[-1], name[:-1]
    # a table written under one of the elements has no inline form to move into, and the array
    # would leave its header naming a value that no dotted key can extend
    if _has_tables_below(document, name) or _written_by_a_key(document, parent):
        return
    # which element of the parent array a child belongs to is what the order it is written in says,
    # and one array holding every child would say it belongs to the first
    if sum(1 for section in document.sections if section.name == parent) > 1:
        return
    written = [section for section in document.sections if section.kind == "array" and section.name == name]
    # an array of nothing but empty elements says no more as `[ {}, {} ]` than written out
    if all(not section.entries for section in written):
        return
    # a comment past the first key would end up inside the braces, where the rest of the line after
    # it would be swallowed. A disabled key is one the comment beside it speaks for, wherever it
    # sits, and a member of an inline table has no line of its own to carry that
    if any(_holds_a_comment(section) for section in written):
        return

    members: list[Member] = []
    for section in written:
        table = InlineTable(entries=[Entry(key=entry.key, value=entry.value) for entry in section.entries])
        # folding a table too wide for one line would bury it, so it stays written out
        if not fits_one_line(Entry(key=(field,), value=table), width.column, width.indent):
            return
        members.append(Member(value=table, lead=_lead_comments(section)))

    # the parent has to be there before the sections holding the members are dropped
    _ensure_exists(document, parent)
    document.sections = [section for section in document.sections if section.name != name]
    at = _index_of(document, parent)
    if at is None:  # pragma: no cover - the parent was just written out
        return
    document.sections[at].entries.append(Entry(key=(field,), value=Array(members=members)))


def _leading_segments(entry: Entry, name: KeyPath, wanted: Wanted) -> KeyPath | None:
    """The segments of a dotted key that become a header of their own.

    The shortest run `wanted` names, so a table stays where it is written until something asks for
    it, and the name that asks for one below it is the one that gets it.
    """
    for width in range(1, len(entry.key)):
        head = entry.key[:width]
        if wanted((*name, *head)):
            return head
    return None


def _deepest_first(document: Document, root: KeyPath, skip: Sequence[KeyPath]) -> list[KeyPath]:
    """The tables below `root`, deepest last so folding pops them off the end.

    Tables at the same depth fold in the order they were written, which is the order they end up in.
    """
    names: list[KeyPath] = []
    seen: set[KeyPath] = set()
    for section in reversed(document.sections):
        name = section.name
        if len(name) <= len(root) or not _is_below(name, root) or name in skip or name in seen:
            continue
        seen.add(name)
        names.append(name)
    names.sort(key=len)
    return names


def _ensure_exists(document: Document, name: KeyPath) -> None:
    """Write out `[name]` when the file only ever named tables below it."""
    if _index_of(document, name) is not None:
        return
    at = next((at for at, section in enumerate(document.sections) if _is_below(section.name, name)), None)
    if at is None:
        return
    # a header the file never wrote carries nothing of its own: what led the table below it, and
    # whatever was written beside that header, stay with the table they were written for
    document.sections.insert(at, Section(name=name, kind="table"))


def _is_array_of_tables(document: Document, name: KeyPath) -> bool:
    return any(section.kind == "array" and section.name == name for section in document.sections)


def _can_hold(document: Document, name: KeyPath) -> bool:
    """Whether a table folded under `name` would land where the file put it."""
    matches = [section for section in document.sections if section.name == name]
    if not matches:
        return not _written_by_a_key(document, name)
    return matches[0].kind == "table" and len(matches) == 1


def _written_by_a_key(document: Document, name: KeyPath) -> bool:
    """Whether a dotted key elsewhere already writes the table out.

    A header for it would then say the same table twice. The sections at or below the name are the
    ones being folded away, so what they hold is what the header comes to stand for.
    """
    if any(_is_below(entry.key, name) for entry in document.root):
        return True
    return any(
        _is_below((*section.name, *entry.key), name)
        for section in document.sections
        if section.name[: len(name)] != name
        for entry in section.entries
    )


def _movable(document: Document, name: KeyPath) -> bool:
    """Whether the name is written once, as a plain table."""
    matches = [section for section in document.sections if section.name == name]
    return len(matches) == 1 and matches[0].kind == "table"


def _has_tables_below(document: Document, name: KeyPath) -> bool:
    return any(_is_below(section.name, name) for section in document.sections)


def _is_below(name: KeyPath, wanted: KeyPath) -> bool:
    """Whether the name sits under `wanted`, compared segment by segment."""
    return len(name) > len(wanted) and name[: len(wanted)] == wanted


def _index_of(document: Document, name: KeyPath) -> int | None:
    return next((at for at, section in enumerate(document.sections) if section.name == name), None)


def _empty_table_entry(leaf: KeyPath, section: Section) -> Entry:
    """An emptied sub-table still has to say it was there, as `sub = {}`."""
    return Entry(key=leaf, value=InlineTable(), lead=list(section.lead), comment=section.comment)


def _holds_a_comment(section: Section) -> bool:
    """Whether anything under the header carries a comment no inline table could keep."""
    return any(_has_comment(entry) for entry in section.entries[1:]) or any(
        is_enabled_here(entry) for entry in section.entries
    )


def _has_comment(entry: Entry) -> bool:
    return entry.comment is not None or any(piece for piece in entry.lead)


def _lead_comments(section: Section) -> list[str]:
    """The comments above the header and above or beside its first key, moved to lead the value."""
    first = section.entries[0] if section.entries else None
    texts = [piece for piece in section.lead if piece]
    if section.comment:
        texts.append(section.comment)
    if first is not None:
        texts.extend(piece for piece in first.lead if piece)
        if first.comment:
            texts.append(first.comment)
    return texts
