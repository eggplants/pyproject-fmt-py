"""Which `Programming Language :: Python` classifiers a `requires-python` range implies.

A minor version is supported when some release in that series satisfies every clause of the range.
An interpreter of the series says its version as `major.minor.micro`, so the series is a window
over the micro versions one of them can have: each clause narrows the window, and what is left is
what one interpreter can report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Literal, TypeAlias

from ..pep440 import Version, written_number
from ..pep508 import VersionOp

if TYPE_CHECKING:
    from collections.abc import Sequence

#: Python 2 stopped at 2.7, so nothing above it names a release.
PYTHON_2_MINORS = 7

#: The operators that say how old a release may be, which gives a range a floor of its own.
LOWER_BOUNDS = frozenset({">=", ">", "==", "===", "~="})

#: What the generated classifiers are written under.
PREFIX = "Programming Language :: Python :: 3"

ONLY_PYTHON_3 = "Programming Language :: Python :: 3 :: Only"


@dataclass(frozen=True)
class Supported:
    """What the project says it supports.

    Attributes:
        minors: The Python 3 minor versions some release of which the range admits.
        write_from: The oldest minor worth writing down. A range says how old a release may be only
            where it names a lower bound; where it does not, the configured minimum decides how far
            back the file is given classifiers, while every minor the range admits is still one the
            file may keep.
        only_python_3: Whether Python 3 is the only major the range admits.
    """

    minors: tuple[int, ...]
    write_from: int
    only_python_3: bool

    def must_have(self) -> set[str]:
        """The classifiers the range implies."""
        # a project no Python 3 release satisfies is not a Python 3 project, and neither is one a
        # Python 2 release still runs
        held = {ONLY_PYTHON_3} if self.minors and self.only_python_3 else set()
        held.update(f"{PREFIX}.{minor}" for minor in self.minors)
        return held

    def worth_writing(self) -> set[str]:
        """The ones worth writing down where the file does not already name them."""
        return {text for text in self.must_have() if _is_worth_writing(text, self.write_from)}


def _is_worth_writing(text: str, write_from: int) -> bool:
    """Whether the classifier names a minor old enough to be worth writing where none is named."""
    held = text.removeprefix(f"{PREFIX}.")
    if held == text or not held.isdigit():
        return True
    return int(held) >= write_from


def read_specifiers(text: str) -> list[VersionOp] | None:
    """The clauses of a specifier set, or None when the text is not one this can read."""
    held = []
    for part in text.split(","):
        try:
            held.append(VersionOp.parse(part))
        except ValueError:
            return None
    return held


def supported(
    requires_python: str | None,
    max_supported_python: tuple[int, int],
    min_supported_python: tuple[int, int],
) -> Supported | None:
    """What the range admits, or None where the text says something this cannot read."""
    if requires_python is None:
        # with nothing said about it, what the formatter was configured with stands
        return Supported(
            minors=tuple(range(min_supported_python[1], max_supported_python[1] + 1)),
            write_from=min_supported_python[1],
            only_python_3=True,
        )
    clauses = read_specifiers(requires_python)
    if clauses is None:
        # a constraint this cannot read still says what the project supports, and the configured
        # window would say something else in its place
        return None
    return Supported(
        minors=tuple(
            minor for minor in range(max_supported_python[1] + 1) if series_holds_a_release(clauses, 3, minor)
        ),
        write_from=0 if any(clause.op in LOWER_BOUNDS for clause in clauses) else min_supported_python[1],
        # `3 :: Only` says no other major runs it, which a range admitting a Python 2 does not
        only_python_3=not any(series_holds_a_release(clauses, 2, minor) for minor in range(PYTHON_2_MINORS + 1)),
    )


def series_holds_a_release(clauses: Sequence[VersionOp], major: int, minor: int) -> bool:
    """Whether one release of `major.minor` satisfies every clause."""
    window = _Window()
    for clause in clauses:
        # `===` compares the text rather than the version it reads as, so an interpreter satisfies
        # it only where its own three numbers are written that way
        if clause.op == "===":
            micro = _names_a_micro(clause.literal, major, minor)
            if micro is None:
                return False
            window.only_micro(micro)
            continue
        if clause.version is None:  # pragma: no cover - only `===` holds text no version reads
            continue
        window.narrow(clause.op, clause.version, major, minor)
    return window.holds_a_release()


def _names_a_micro(literal: str, major: int, minor: int) -> int | None:
    """The micro version the text says, where it says a release of that series."""
    head = f"{major}.{minor}."
    return written_number(literal[len(head) :]) if literal.startswith(head) else None


@dataclass
class _Window:
    """What a release of one minor series may name as its micro version."""

    low: tuple[int, bool] | None = None
    high: tuple[int, bool] | None = None
    excluded: set[int] = field(default_factory=set)
    empty: bool = False

    def narrow(self, op: str, version: Version, major: int, minor: int) -> None:
        """Hold the window to what the clause leaves of it."""
        # an ordinary Python release names no epoch, so a bound that names one is above every one
        # of them and a bound below it rules out none
        if version.epoch:
            if op not in {"<=", "<", "!="}:
                self.empty = True
            return
        named = (_at(version.release, 0), _at(version.release, 1))
        tail = version.release[2:]
        if op in {">=", ">"}:
            self._above(op, version, named, tail, (major, minor))
        elif op in {"<=", "<"}:
            self._below(op, version, named, tail, (major, minor))
        elif op in {"==", "==="}:
            self._only(version, named, tail, major, minor)
        elif op == "!=":
            self._without(version, named, tail, major, minor)
        elif op == "~=":
            self._compatible(version, named, tail, major, minor)

    def _above(
        self, op: str, version: Version, named: tuple[int, int], tail: list[int], series: tuple[int, int]
    ) -> None:
        if named > series:
            self.empty = True
        elif named == series:
            held = _compare_micro(_micro_of(tail), tail, version)
            self.at_least(_micro_of(tail), inclusive=held > 0 or (held == 0 and op == ">="))

    def _below(
        self, op: str, version: Version, named: tuple[int, int], tail: list[int], series: tuple[int, int]
    ) -> None:
        if named < series:
            self.empty = True
        elif named == series:
            held = _compare_micro(_micro_of(tail), tail, version)
            self.at_most(_micro_of(tail), inclusive=held < 0 or (held == 0 and op == "<="))

    def _only(self, version: Version, named: tuple[int, int], tail: list[int], major: int, minor: int) -> None:
        """`==`, which names one release or, with a wildcard, everything the numbers open with."""
        if version.has_wildcard:
            self._by_wildcard(version.release, major, minor)
            return
        # no release of the series is the one a pre, dev, post or local version names
        if named != (major, minor) or _compare_micro(_micro_of(tail), tail, version) != 0:
            self.empty = True
            return
        self.only_micro(_micro_of(tail))

    def _without(self, version: Version, named: tuple[int, int], tail: list[int], major: int, minor: int) -> None:
        """`!=`, which rules out one release or, with a wildcard, everything the numbers open with."""
        if version.has_wildcard:
            held = _wildcard_match(version.release, major, minor)
            if held == SERIES:
                self.empty = True
            elif held is not None:
                self.excluded.add(held)
            return
        # a version outside the series rules out nothing in it, and neither does one no release of
        # the series is written as
        if named == (major, minor) and _compare_micro(_micro_of(tail), tail, version) == 0:
            self.excluded.add(_micro_of(tail))

    def _compatible(self, version: Version, named: tuple[int, int], tail: list[int], major: int, minor: int) -> None:
        """`~=X.Y.Z` says `>=X.Y.Z` and `==X.Y.*`, so it names the series one component short."""
        self._by_wildcard(version.release[:-1], major, minor)
        if self.empty:
            return
        if named > (major, minor):
            self.empty = True
        elif named == (major, minor):
            self.at_least(_micro_of(tail), inclusive=_compare_micro(_micro_of(tail), tail, version) >= 0)

    def _by_wildcard(self, release: Sequence[int], major: int, minor: int) -> None:
        """Hold the window to what the numbers a wildcard opens with leave of the series."""
        held = _wildcard_match(release, major, minor)
        if held is None:
            self.empty = True
        elif held != SERIES:
            self.only_micro(held)

    def only_micro(self, micro: int) -> None:
        """Hold the window to the one release naming this micro version."""
        self.at_least(micro, inclusive=True)
        self.at_most(micro, inclusive=True)

    def at_least(self, bound: int, *, inclusive: bool) -> None:
        """Raise the floor, where the bound says more than what is already there."""
        if self.low is None or bound > self.low[0] or (bound == self.low[0] and self.low[1] and not inclusive):
            self.low = (bound, inclusive)

    def at_most(self, bound: int, *, inclusive: bool) -> None:
        """Lower the ceiling, where the bound says more than what is already there."""
        if self.high is None or bound < self.high[0] or (bound == self.high[0] and self.high[1] and not inclusive):
            self.high = (bound, inclusive)

    def holds_a_release(self) -> bool:
        """Whether some micro version lies inside the window and is not one the clauses rule out."""
        if self.empty:
            return False
        candidate = 0 if self.low is None else (self.low[0] if self.low[1] else self.low[0] + 1)
        if self.high is None:
            highest = None
        elif self.high[1]:
            highest = self.high[0]
        elif self.high[0] == 0:
            return False
        else:
            highest = self.high[0] - 1
        # each turn either finds a release or passes one the clauses rule out, and they rule out
        # only so many
        while True:
            if highest is not None and candidate > highest:
                return False
            if candidate not in self.excluded:
                return True
            candidate += 1


#: What a wildcard matches when it matches every release of the series.
SERIES: Final = "series"

#: What the numbers a wildcard opens with match: every release of the series, one micro version of
#: it, or none of it.
Match: TypeAlias = "Literal['series'] | int | None"


def _wildcard_match(release: Sequence[int], major: int, minor: int) -> Match:
    """What the numbers a wildcard opens with match in one minor series.

    A prefix is met by a release that opens with it once both are written out to the same length,
    so the zeros a prefix ends with match a release that leaves them unwritten.
    """
    if _at(release, 0) != major:
        return None
    if len(release) < 2:  # noqa: PLR2004 - a series is named by two numbers
        return SERIES
    if release[1] != minor:
        return None
    rest = release[2:]
    if not rest:
        return SERIES
    return rest[0] if all(held == 0 for held in rest[1:]) else None


def _micro_of(tail: Sequence[int]) -> int:
    """The micro version the numbers name, which is zero where they name none."""
    return tail[0] if tail else 0


def _compare_micro(micro: int, tail: Sequence[int], version: Version) -> int:
    """Where an interpreter's micro version stands against a version of the same series.

    A release the file names before the final one is under it, and one it names after is above it,
    so the plain release sits on one side of the version however it was written.
    """
    if tail:
        held = _sign(micro - tail[0])
        if held == 0 and not all(number == 0 for number in tail[1:]):
            held = -1
    else:
        held = _sign(micro)
    if held != 0:
        return held
    # PEP 440 reads the suffixes in this order: a pre release stays under the final one whatever
    # follows it, a post release stays above it, and a dev release on its own is under it
    if version.pre is not None:
        return 1
    if version.post is not None:
        return -1
    if version.dev is not None:
        return 1
    if version.local is not None:
        return -1
    return 0


def _sign(held: int) -> int:
    return (held > 0) - (held < 0)


def _at(release: Sequence[int], index: int) -> int:
    return release[index] if index < len(release) else 0
