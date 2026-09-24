"""Reordering and rewriting the members of an array.

Each member owns the comments written above it, so sorting is ordinary list work: a member's
comments move with it, and dropping one leaves the array as open or as closed as the file wrote it.
Nothing sorts across a `# Group:` marker.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from .document import Array, Scalar
from .ordering import group_ranges, take_marker
from .sorting import natural_lexical_key

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from .document import Member, Value

_K = TypeVar("_K")

#: Nothing moves in a run of one.
_ENOUGH_TO_SORT = 2


def text_of(member: Member) -> str | None:
    """The characters a member holds, or None where it holds something other than a string."""
    value = member.value
    return value.text if isinstance(value, Scalar) and value.kind == "string" else None


def sort(array: Array, key_of: Callable[[Member], _K | None]) -> None:
    """Sort members within each group, holding the groups in the order they were written.

    A member the key function cannot read has nothing to sort by, and the array it sits in says
    what it says by the order it was written in, so nothing moves.
    """
    keys: list[_K] = []
    for member in array.members:
        key = key_of(member)
        if key is None:
            return
        keys.append(key)
    placed: list[Member] = []
    for held in _member_ranges(array.members):
        run = [(array.members[at], keys[at]) for at in held]
        if not run:
            continue
        # the marker names the group, not the member written under it, so it stays on top of it
        marker = take_marker(run[0][0].lead)
        run.sort(key=lambda pair: pair[1])
        at = len(placed)
        placed.extend(member for member, _ in run)
        placed[at].lead[:0] = marker
    array.members = placed


def sort_placed(array: Array, key_of: Callable[[Member], _K | None]) -> None:
    """Sort what the key function can read among the places that are left.

    A member it cannot read holds the place the file gave it, since what such an entry generates
    is read where it sits while the names written around it move.
    """
    placed: list[Member] = []
    for held in _member_ranges(array.members):
        placed.extend(_placed_run([array.members[at] for at in held], key_of))
    array.members = placed


def sort_runs(
    array: Array,
    stays: Callable[[Member], bool],
    key_of: Callable[[Member], _K | None],
) -> None:
    """Sort each run of members between the ones `stays` holds where they are.

    A member whose place is part of what the file says, as an `include-group` is where the group it
    pulls in belongs, keeps it; only what is written between two of those moves.
    """
    placed: list[Member] = []
    run: list[Member] = []
    for member in array.members:
        if stays(member):
            placed.extend(_sorted_run(run, key_of))
            run = []
            placed.append(member)
        else:
            run.append(member)
    placed.extend(_sorted_run(run, key_of))
    array.members = placed


def sort_strings(array: Array, to_key: Callable[[str], object]) -> None:
    """Sort a string array by the key each member maps to."""
    sort(array, lambda member: None if (text := text_of(member)) is None else to_key(text))


def sort_names_in(value: Value) -> None:
    """Sort a value that is a list of names, and leave it alone otherwise."""
    if isinstance(value, Array):
        sort_strings(value, lambda text: natural_lexical_key(text.lower()))


def dedupe_strings_in(value: Value, to_key: Callable[[str], object] = str) -> None:
    """Drop the later members of a string array whose key repeats an earlier one."""
    if not isinstance(value, Array):
        return
    seen: set[object] = set()

    def first_of_its_key(member: Member) -> bool:
        text = text_of(member)
        if text is None:
            return True
        key = to_key(text)
        if key in seen:
            return False
        seen.add(key)
        return True

    remove_members(value, first_of_its_key)


def map_strings(value: Value, rewrite: Callable[[str], str]) -> None:
    """Rewrite the text of every string member of an array, leaving anything else alone."""
    if not isinstance(value, Array):
        return
    for member in value.members:
        held = member.value
        if isinstance(held, Scalar) and held.kind == "string":
            written = rewrite(held.text)
            if written != held.text:
                held.replace_text(written)


def retain_strings(value: Value, keep: Callable[[str], bool]) -> None:
    """Drop the members of a string array whose text the predicate rejects."""
    if isinstance(value, Array):
        remove_members(value, lambda member: (text := text_of(member)) is None or keep(text))


def remove_members(array: Array, keep: Callable[[Member], bool]) -> None:
    """Drop the members the predicate rejects, moving what they said to whatever follows them.

    A dropped member's comments are about what the file still says around them, and each keeps a
    line of its own since a comment runs to the end of the line it opens.
    """
    last = len(array.members) - 1
    last_kept = True
    carried: list[str] = []
    kept: list[Member] = []
    for index, member in enumerate(array.members):
        if keep(member):
            member.lead[:0] = carried
            carried = []
            kept.append(member)
            continue
        last_kept = last_kept and index != last
        carried.extend(piece for piece in member.lead if piece)
        if member.comment:
            carried.append(member.comment)
    array.trailing[:0] = carried
    array.members = kept
    # an array stays open on the comma that closes it, and dropping the member that comma followed
    # closes the array with it
    array.trailing_comma = array.trailing_comma and last_kept


def _member_ranges(members: Sequence[Member]) -> list[range]:
    return group_ranges([member.lead for member in members])


def _sorted_run(members: list[Member], key_of: Callable[[Member], _K | None]) -> list[Member]:
    run = Array(members=list(members))
    sort(run, key_of)
    return run.members


def _placed_run(members: list[Member], key_of: Callable[[Member], _K | None]) -> list[Member]:
    ranked = [(at, key) for at, member in enumerate(members) if (key := key_of(member)) is not None]
    if len(ranked) < _ENOUGH_TO_SORT:
        return members
    # the marker names the group, not the member written under it, so it stays on top of it
    marker = take_marker(members[0].lead)
    slots = [at for at, _ in ranked]
    ranked.sort(key=lambda pair: pair[1])
    placed = list(members)
    for slot, (at, _) in zip(slots, ranked, strict=True):
        placed[slot] = members[at]
    placed[0].lead[:0] = marker
    return placed
