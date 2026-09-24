"""Finding tables by name, and ordering the keys of the ones a rule speaks for.

TOML gives every spelling of a table the same name, so a rule reads the same keys whichever one the
file chose: `[tool.ruff] lint.select`, `[tool.ruff.lint] select` and `[tool.ruff] lint = { … }` all
name `tool.ruff.lint.select`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias

from .arrays import sort_names_in
from .disabled import is_enabled_here
from .document import Array, InlineTable
from .keys import dotted_name
from .ordering import group_ranges, is_named, rank, reorder_keys, take_marker

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from .document import Document, Entry, Section, Value
    from .keys import KeyPath

#: What table a key belongs to, where it belongs to one the caller is ordering.
TableOf: TypeAlias = "Callable[[KeyPath], KeyPath | None]"


def for_keys_under(document: Document, path: KeyPath, visit: Callable[[str, Value], None]) -> None:
    """Run `visit` over everything written under `path`, with the rest of its name below `path`."""

    def take(key: KeyPath, value: Value, under: KeyPath) -> None:
        named = (*under, *key)
        # a key on the way to the table says nothing about it, but what it holds may
        if not (_starts_with(named, path) or _starts_with(path, named)):
            return
        if _starts_with(named, path) and len(named) > len(path):
            visit(dotted_name(named[len(path) :]), value)
        if isinstance(value, InlineTable):
            for entry in value.entries:
                take(entry.key, entry.value, named)

    for under, entry in active_entries(document):
        take(entry.key, entry.value, under)


def reorder_under(document: Document, path: KeyPath, order: Sequence[str], keeps_order: Sequence[str] = ()) -> None:
    """Put the keys of the table `path` names in `order`, wherever the file wrote them."""
    _Ordering(path=path, order=order, keeps_order=keeps_order).apply(document)


def reorder_tables_of(
    document: Document,
    table_of: TableOf,
    order: Sequence[str],
    keeps_order: Sequence[str] = (),
) -> None:
    """`reorder_under` for every table `table_of` names, reading the file once however many."""
    _Ordering(path=(), order=order, keeps_order=keeps_order, table_of=table_of).apply(document)


@dataclass(frozen=True)
class _Ordering:
    """What ordering a table asks of every container that holds a key of it.

    The table is either the one a caller named, or whichever one each key belongs to.
    """

    path: KeyPath
    order: Sequence[str]
    keeps_order: Sequence[str]
    table_of: TableOf | None = None

    def apply(self, document: Document) -> None:
        """Order every run of entries the document holds."""
        self.entries(document.root, ())
        for section in document.sections:
            self.entries(section.entries, section.name)

    def _table(self, named: KeyPath) -> KeyPath | None:
        """The table a key belongs to, where it belongs to one being ordered."""
        path = self.table_of(named) if self.table_of is not None else self.path
        if path is None:
            return None
        return path if len(named) > len(path) and _starts_with(named, path) else None

    def entries(self, entries: list[Entry], under: KeyPath) -> None:
        """Order one run of entries, and the tables written inside their values."""
        for entry in entries:
            self.members(entry.value, (*under, *entry.key))
        if not self.speaks_for(under):
            return
        # a marker names the group it opens, so the entries of one group sort among themselves
        for group in group_ranges([entry.lead for entry in entries]):
            held = self._by_table(under, group, lambda at: entries[at].key)
            if not held:
                continue
            # the marker names the group, not the entry it was written above, so it stays on top
            opens = any(slots[0] == group.start for _, slots in held)
            marker = take_marker(entries[group.start].lead) if opens else None
            for table, slots in held:
                _sort_slots(entries, slots, lambda entry, table=table: self.ranked(_below(under, entry.key, table)))
            if marker:
                entries[group.start].lead[:0] = marker
            # reordering breaks up whatever grouping the empty lines marked, so they go and the
            # comments that belong to an entry travel with it
            for at in (slot for _, slots in held for slot in slots):
                if not is_enabled_here(entries[at]):
                    entries[at].lead[:] = [piece for piece in entries[at].lead if piece]

    def members(self, value: Value, under: KeyPath) -> None:
        """Order the members of a table the file wrote as a value, and of the tables inside it."""
        if not isinstance(value, InlineTable):
            return
        # a table neither on the way to the one being ordered nor under it holds none of its keys,
        # and an order saying nothing about a table says nothing about the tables inside it either
        if not self.reaches(under) or not self.speaks_for(under):
            return
        for entry in value.entries:
            self.members(entry.value, (*under, *entry.key))
        held = self._by_table(under, range(len(value.entries)), lambda at: value.entries[at].key)
        for table, slots in held:
            _sort_slots(value.entries, slots, lambda entry, table=table: self.ranked(_below(under, entry.key, table)))

    def ranked(self, tail: KeyPath) -> tuple[int, str]:
        """Where a key sits among the ones it is sorted against."""
        name = dotted_name(tail)
        # a sort that keeps equal keys where they were is what holds a run in place, so the keys of
        # an ordered name are all given the same one
        held = any(is_named(name, kept) for kept in self.keeps_order)
        return rank(name, self.order), "" if held else name.lower()

    def speaks_for(self, under: KeyPath) -> bool:
        """Whether this ordering speaks for the keys of the table `under` names.

        A table below the one being ordered has keys of its own, and the order speaks for them only
        where it names one: `lint.select` says where `select` sits inside `lint`, while `authors`
        says where the authors sit and nothing about what one holds.
        """
        if self.table_of is not None:
            held = self.table_of(under)
            if held is None:
                return True
        else:
            held = self.path
        if not _starts_with(under, held):
            return True
        tail = under[len(held) :]
        if not tail:
            return True
        named = f"{dotted_name(tail)}."
        return any(wanted.startswith(named) for wanted in self.order)

    def reaches(self, under: KeyPath) -> bool:
        """Whether a container can hold a key of the table being ordered."""
        if self.table_of is not None:
            return True
        return _starts_with(under, self.path) or _starts_with(self.path, under)

    def _by_table(
        self,
        under: KeyPath,
        slots: range,
        key_at: Callable[[int], KeyPath],
    ) -> list[tuple[KeyPath, list[int]]]:
        """The slots of one run that hold a key being ordered, gathered under their table."""
        held: dict[KeyPath, list[int]] = {}
        for at in slots:
            table = self._table((*under, *key_at(at)))
            if table is not None:
                held.setdefault(table, []).append(at)
        return list(held.items())


#: Nothing moves in a run of one.
_ENOUGH_TO_SORT = 2


def _below(under: KeyPath, key: KeyPath, table: KeyPath) -> KeyPath:
    """What a key names below the table it belongs to."""
    return (*under, *key)[len(table) :]


def _starts_with(name: KeyPath, prefix: KeyPath) -> bool:
    return len(name) >= len(prefix) and name[: len(prefix)] == prefix


def _sort_slots(items: list, slots: Sequence[int], key_of: Callable) -> None:
    """Sort what sits at `slots` among itself, leaving everything around it where the file wrote it."""
    if len(slots) < _ENOUGH_TO_SORT:
        return
    picked = sorted((items[at] for at in slots), key=key_of)
    for at, item in zip(slots, picked, strict=True):
        items[at] = item


def active_entries(document: Document) -> list[tuple[KeyPath, Entry]]:
    """Every entry a rule may rewrite: a key the file wrote as a comment is not one of them."""
    return [(under, entry) for under, entry in document.entries() if not is_enabled_here(entry)]


def first_section(document: Document, name: KeyPath) -> Section | None:
    """The first section the file wrote under `name`, where it wrote one."""
    return next((section for section in document.sections if section.name == name), None)


def for_value_at(document: Document, path: KeyPath, visit: Callable[[Value], None]) -> None:
    """Run `visit` over the value written at exactly `path`."""
    for under, entry in document.entries():
        if (*under, *entry.key) == path:
            visit(entry.value)


def for_array_elements(
    document: Document,
    path: KeyPath,
    key_order: Sequence[str],
    visit: Callable[[str, Value], None] = lambda _key, _value: None,
) -> None:
    """Apply one rule to every element of an array of tables, however the file writes it.

    An element is either one of the `[[path]]` headers the file wrote or one of the inline tables
    the short format folds them into. `visit` sees every key of every element and the value it
    holds, and each element's keys end up in `key_order`.
    """
    for section in document.sections:
        if section.kind == "array" and section.name == path:
            for entry in section.entries:
                visit(dotted_name(entry.key), entry.value)
            reorder_keys(section.entries, key_order)

    def in_array(value: Value) -> None:
        if not isinstance(value, Array):
            return
        for member in value.members:
            held = member.value
            if not isinstance(held, InlineTable):
                continue
            for entry in held.entries:
                visit(dotted_name(entry.key), entry.value)
            held.entries.sort(key=lambda entry: _element_rank(entry.key, key_order))

    for_value_at(document, path, in_array)


def sort_names_under(document: Document, name: KeyPath) -> None:
    """Sort both sides of a table that pairs names with lists of names."""
    section = first_section(document, name)
    if section is None:
        return
    for entry in section.entries:
        sort_names_in(entry.value)
    reorder_keys(section.entries, ())


def _element_rank(key: KeyPath, key_order: Sequence[str]) -> tuple[int, str]:
    name = dotted_name(key)
    return rank(name, key_order), name.lower()


def for_entries(section: Section, visit: Callable[[str, Value], None]) -> None:
    """Run `visit` over every key of one section and the value it holds."""
    for entry in section.entries:
        visit(dotted_name(entry.key), entry.value)


def reorder_array_tables_at(document: Document, path: KeyPath, order: Sequence[str]) -> None:
    """Put the keys of every table written inside the array at `path` in order.

    The path already says which table the array holds, so what is inside one does not have to name
    itself for its keys to be ordered.
    """

    def in_array(value: Value) -> None:
        if not isinstance(value, Array):
            return
        for member in value.members:
            if isinstance(member.value, InlineTable):
                member.value.entries.sort(key=lambda entry: _element_rank(entry.key, order))

    for_value_at(document, path, in_array)


@dataclass(frozen=True)
class InlineSchema:
    """An inline table recognized by a key only it carries, which fixes the order of the rest.

    Attributes:
        discriminator: The key that says the table is one of these.
        key_order: Where each of its keys sits.
    """

    discriminator: str
    key_order: Sequence[str]


def reorder_inline_tables(document: Document, path: KeyPath, schemas: Sequence[InlineSchema]) -> None:
    """Order the keys of every inline table a schema recognizes, among the values under `path`.

    A discriminator names a key one tool writes, not one no other tool may: the table a rule
    belongs to is what says the rule is about it.
    """
    for under, entry in active_entries(document):
        if _starts_with((*under, *entry.key), path):
            _order_within(entry.value, schemas)


def _order_within(value: Value, schemas: Sequence[InlineSchema]) -> None:
    if isinstance(value, Array):
        for member in value.members:
            _order_within(member.value, schemas)
        return
    if not isinstance(value, InlineTable):
        return
    for entry in value.entries:
        _order_within(entry.value, schemas)
    held = {dotted_name(entry.key) for entry in value.entries}
    schema = next((schema for schema in schemas if schema.discriminator in held), None)
    if schema is None:
        return
    value.entries.sort(key=lambda entry: _element_rank(entry.key, schema.key_order))


def for_names_under(document: Document, path: KeyPath, visit: Callable[[KeyPath, Entry], None]) -> None:
    """Run `visit` over every key written under `path`, with the rest of its name below `path`.

    A rule reading a name this way sees the segments the file wrote, so a name quoted because it
    holds a dot is the one segment it is rather than the two a dotted path would read.
    """

    def take(entry: Entry, under: KeyPath) -> None:
        named = (*under, *entry.key)
        if not (_starts_with(named, path) or _starts_with(path, named)):
            return
        if _starts_with(named, path) and len(named) > len(path):
            visit(named[len(path) :], entry)
        if isinstance(entry.value, InlineTable):
            for held in entry.value.entries:
                take(held, named)

    for under, entry in active_entries(document):
        take(entry, under)


def headers_below(document: Document, prefix: KeyPath) -> list[str]:
    """The names written one level below `prefix`, each the one segment the file gave it."""
    names: list[str] = []
    for section in document.sections:
        if len(section.name) > len(prefix) and section.name[: len(prefix)] == prefix:
            held = section.name[len(prefix)]
            if held not in names:
                names.append(held)
    return sorted(names)


def for_entry_runs(document: Document, path: KeyPath, visit: Callable[[list[Entry], KeyPath], None]) -> None:
    """Run `visit` over every run of entries that could hold a key written under `path`."""
    visit(document.root, ())
    for section in document.sections:
        if _starts_with(section.name, path) or _starts_with(path, section.name):
            visit(section.entries, section.name)


def for_key_paths_under(document: Document, path: KeyPath, visit: Callable[[KeyPath, Entry], None]) -> None:
    """Run `visit` over every key written under `path`, with the whole path it names."""

    def take(entry: Entry, under: KeyPath) -> None:
        named = (*under, *entry.key)
        if not (_starts_with(named, path) or _starts_with(path, named)):
            return
        if _starts_with(named, path) and len(named) > len(path):
            visit(named, entry)
        if isinstance(entry.value, InlineTable):
            for held in entry.value.entries:
                take(held, named)

    for under, entry in active_entries(document):
        take(entry, under)


def every_value(document: Document) -> list[Value]:
    """Every value the document holds, in the order it was written."""
    return [entry.value for _under, entry in document.entries()]


def rename_under(document: Document, path: KeyPath, aliases: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    """Rewrite the keys of `path` that an alias names, and say which renames were made.

    A file that already spells a key the canonical way keeps both as written: renaming the older
    spelling on top of it would say the same key twice, which no TOML document can.
    """
    taken: list[str] = []
    for_names_under(document, path, lambda tail, _entry: taken.append(dotted_name(tail)))
    renamed: list[tuple[str, str]] = []
    held = dict(aliases)

    def rename(tail: KeyPath, entry: Entry) -> None:
        # an alias names one key of the table, so a name written below one is not the key it moves
        if len(tail) != 1 or tail[0] not in held:
            return
        to = held[tail[0]]
        if to in taken:
            return
        entry.key = (*entry.key[:-1], to)
        taken.append(to)
        renamed.append((tail[0], to))

    for_names_under(document, path, rename)
    return renamed


def rename_tables_of(
    document: Document,
    table_of: TableOf,
    aliases: Sequence[tuple[str, str]],
) -> list[tuple[KeyPath, str, str]]:
    """`rename_under` for every table `table_of` names, reading the file once however many."""
    taken: list[KeyPath] = []
    for_key_paths_under(document, (), lambda named, _entry: taken.append(named))
    renamed: list[tuple[KeyPath, str, str]] = []
    held = dict(aliases)

    def rename(named: KeyPath, entry: Entry) -> None:
        table = table_of(named)
        if table is None:
            return
        tail = named[len(table) :]
        if len(tail) != 1 or tail[0] not in held:
            return
        to = held[tail[0]]
        if (*table, to) in taken:
            return
        entry.key = (*entry.key[:-1], to)
        renamed.append((table, tail[0], to))
        taken.append((*table, to))

    for_key_paths_under(document, (), rename)
    return renamed
