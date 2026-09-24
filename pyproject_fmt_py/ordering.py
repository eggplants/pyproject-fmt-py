"""Putting tables and keys in order.

A document already groups entries under the header they were written below, so a section is the
unit that moves and ordering keys is a sort over a section's entries. An entry carries the comments
written above it, so nothing has to be spliced back into place.

Sorting never crosses a `# Group:` marker: the marker opens a range of its own and holds it apart
from the one before it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .disabled import is_enabled_here
from .keys import dotted_name, render_key

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

    from .document import Document, Entry, Section
    from .keys import KeyPath

#: What opens a group, whatever case the comment writes it in.
_MARKER = "group:"


def is_group_marker(comment: str) -> bool:
    """Whether a comment opens a group, as `# Group: web`. Case does not matter."""
    return comment.lstrip().removeprefix("#").lstrip()[: len(_MARKER)].lower() == _MARKER


def opens_a_group(lead: Iterable[str]) -> bool:
    """Whether anything written above an item opens a group."""
    return any(piece and is_group_marker(piece) for piece in lead)


def group_ranges(leads: Sequence[Sequence[str]]) -> list[range]:
    """The ranges the `# Group:` markers split a run of items into, read from what leads each."""
    starts = [0]
    starts.extend(index for index, lead in enumerate(leads) if index and opens_a_group(lead))
    starts.append(len(leads))
    return [range(starts[at], starts[at + 1]) for at in range(len(starts) - 1)]


def take_marker(lead: list[str]) -> list[str]:
    """Take the lines up to and including the group marker off what leads an item."""
    last = next((index for index in reversed(range(len(lead))) if lead[index] and is_group_marker(lead[index])), None)
    if last is None:
        return []
    taken = lead[: last + 1]
    del lead[: last + 1]
    return taken


def is_named(name: str, wanted: str) -> bool:
    """Whether the name is `wanted` or a key written under it."""
    return name == wanted or name.startswith(f"{wanted}.")


def rank(key: str, order: Sequence[str]) -> int:
    """Where a key sits in `order`. A key the order does not name sorts after every one it does."""
    return next((at for at, name in enumerate(order) if is_named(key, name)), len(order))


def run_end(path: str, wanted: str) -> int | None:
    """Where `wanted` ends inside the path, when the path names it or something written under it."""
    if path == wanted or path.startswith(f"{wanted}."):
        return len(wanted)
    held = f".{wanted}"
    at = path.find(held)
    if at == -1:
        return None
    end = at + len(held)
    return end if len(path) == end or path[end:].startswith(".") else None


def reorder_keys(entries: list[Entry], order: Sequence[str], keeps_order: Sequence[str] = ()) -> None:
    """Put the entries in `order`, holding anything unnamed after them in alphabetical order.

    A name in `order` also claims the dotted keys beneath it, so `lint` pulls `lint.select` along.
    The keys written under a name in `keeps_order` hold the order the file gave them, since where
    each one sits among the others is part of what it says.
    """
    for held in group_ranges([entry.lead for entry in entries]):
        if not held:
            continue
        start = held.start
        # the marker names the group, not the entry it was written above, so it stays on top of it
        marker = take_marker(entries[start].lead)
        entries[start : held.stop] = sorted(
            entries[start : held.stop],
            key=lambda entry: _key_rank(entry, order, keeps_order),
        )
        entries[start].lead[:0] = marker
    # reordering breaks up whatever grouping the empty lines marked, so they go and the comments
    # that belong to an entry travel with it. A disabled key is a comment the file wrote, and the
    # lines around it are part of what that comment says
    for entry in entries:
        if not is_enabled_here(entry):
            entry.lead[:] = [piece for piece in entry.lead if piece]


def _key_rank(entry: Entry, order: Sequence[str], keeps_order: Sequence[str]) -> tuple[int, str]:
    # the order names keys the way a dispatch name spells them, while what falls outside it sorts
    # the way the file spells them
    name = dotted_name(entry.key)
    # a sort that keeps equal keys where they were is what holds a run in place, so the keys of an
    # ordered name are all given the same one
    held = any(is_named(name, kept) for kept in keeps_order)
    return rank(name, order), "" if held else render_key(entry.key).lower()


def reorder_tables(
    document: Document,
    order: Sequence[str],
    nested_prefixes: Sequence[str],
    key_order: Callable[[KeyPath], Sequence[str] | None],
    keep_order: Callable[[KeyPath], Sequence[str]],
) -> None:
    """Put every table where `order` says it goes, moving what belongs to it along with it."""
    blocks = _blocks(document)
    # a table the order does not name keeps the place its group was first written in, so a file
    # using tools this formatter has no policy for is left as its author arranged it
    seen: dict[KeyPath, int] = {}
    for block in blocks:
        seen.setdefault(base_segments(block[0].name, nested_prefixes), len(seen))
    placed_at: dict[str, int] = {}
    for at, name in enumerate(order):
        placed_at.setdefault(name, at)
    places = _Places(order, tuple(nested_prefixes), placed_at, seen, key_order, keep_order)

    sorted_blocks: list[list[Section]] = []
    for partition in _partitions(blocks):
        # the marker names the group, not the table written under it, so it stays on top of it
        marker = take_marker(partition[0][0].lead)
        partition.sort(key=lambda block: places.rank_of(block[0].name))
        lead = partition[0][0].lead
        opening = next((index for index, piece in enumerate(lead) if piece), len(lead))
        del lead[:opening]
        lead[:0] = marker
        sorted_blocks.extend(partition)

    document.sections = [section for block in sorted_blocks for section in block]
    _respace(document)


@dataclass(frozen=True)
class _Places:
    """Where each table goes, read once for the whole document rather than per comparison."""

    order: Sequence[str]
    nested_prefixes: tuple[str, ...]
    placed_at: dict[str, int]
    seen: dict[KeyPath, int]
    key_order: Callable[[KeyPath], Sequence[str] | None]
    keep_order: Callable[[KeyPath], Sequence[str]]

    def rank_of(self, name: KeyPath) -> tuple[int, int, int, int, str]:
        """What the table sorts by."""
        head = base_segments(name, self.nested_prefixes)
        leaf = dotted_name(name[len(head) :])
        within = rank(leaf, self.key_order(head) or ())
        group = self.seen.get(head, len(self.seen))
        # a sort that keeps equal keys where they were is what holds a run of tables in place, so
        # the ones written under an ordered name are read only as far as that name
        ends = (run_end(leaf, kept) for kept in self.keep_order(head))
        end = next((at for at in ends if at is not None), None)
        last = leaf.lower() if end is None else leaf[:end].lower()
        # the table itself leads the tables written beneath it
        return self._placed(head), group, int(bool(leaf)), within, last

    def _placed(self, head: KeyPath) -> int:
        """Where the order names the table.

        A table is placed by the name it was given, not by a shorter name it happens to start with:
        `env_base.test` is its own table rather than part of `env_base`. One the order does not name
        still belongs among its own kind, so an unknown tool stays with the tools rather than
        falling in among the tables that are nobody's tool.
        """
        base = dotted_name(head)
        if base in self.placed_at:
            return self.placed_at[base]
        nested = bool(head) and head[0] in self.nested_prefixes
        return len(self.order) + (0 if nested else 1)


def base_segments(name: KeyPath, nested_prefixes: Sequence[str]) -> KeyPath:
    """The name a table groups under: one level deeper for the nested prefixes.

    The answer is the segments themselves, not the name they join into: joining first would make
    `tool."a.b"` and `tool.a.b` the same table.
    """
    width = 2 if name and name[0] in nested_prefixes else 1
    return name[: min(width, len(name))]


def _blocks(document: Document) -> list[list[Section]]:
    """The runs of sections that have to move together.

    A `[[name]]` header opens one element of an array, and a `[name.child]` written anywhere below
    it belongs to that element rather than to the name. The two need not sit next to each other, so
    ownership is tracked per array path and survives unrelated tables in between.
    """
    blocks: list[list[Section]] = []
    owners: list[tuple[KeyPath, int]] = []
    for section in document.sections:
        name = section.name
        # the innermost element the header falls under owns it; a longer path is the closer one
        inside = [(path, block) for path, block in owners if len(name) > len(path) and name[: len(path)] == path]
        if inside:
            at = max(inside, key=lambda held: len(held[0]))[1]
            blocks[at].append(section)
        else:
            blocks.append([section])
            at = len(blocks) - 1
        if blocks[at][-1].kind == "array":
            # a new element starts its own scope, so what the previous one owned is out of reach
            owners[:] = [
                (path, block) for path, block in owners if not (len(path) >= len(name) and path[: len(name)] == name)
            ]
            owners.append((name, at))
    document.sections = []
    return blocks


def _partitions(blocks: list[list[Section]]) -> list[list[list[Section]]]:
    """The runs of blocks a `# Group:` marker splits the document into, which sorting must not cross."""
    partitions: list[list[list[Section]]] = []
    for block in blocks:
        if partitions and not opens_a_group(block[0].lead):
            partitions[-1].append(block)
        else:
            partitions.append([block])
    return partitions


def _respace(document: Document) -> None:
    """Set the tables one line apart, since reordering broke whatever spacing the file had."""
    sections = document.sections
    opens_next = [
        not sections[at].entries and sections[at].name != sections[at + 1].name for at in range(len(sections) - 1)
    ]
    for index, section in enumerate(sections):
        section.lead[:] = [piece for piece in section.lead if piece]
        # a header with nothing under it reads as the opening of what follows, so it keeps it close
        if index and not opens_next[index - 1]:
            section.lead.insert(0, "")
