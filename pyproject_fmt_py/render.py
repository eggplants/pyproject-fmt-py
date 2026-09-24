"""Writing a document back out: what goes around `=`, inside brackets, and where an array breaks.

Nothing here decides what the file says, only how wide each line runs. An array closes back up
onto one line unless the file asked otherwise or it would not fit, and the comments inside one are
lined up against its widest member.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .document import Array, Entry, InlineTable, Scalar
from .keys import render_key
from .strings import normalize_quotes
from .width import columns

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .config import Settings
    from .document import Document, Member, Section, Value

#: What sits between a value and the comment closing its line.
COMMENT_GAP = "  "

#: What sits between a key and its value.
AROUND_EQUALS = " = "


@dataclass(frozen=True)
class Written:
    """How wide a value is written.

    Attributes:
        width: The columns it takes in all.
        last_line: The columns of the line it ends on, since a value broken over lines only
            carries that last line into whatever follows it.
        broken: Whether it runs over more than one line.
    """

    width: int = 0
    last_line: int = 0
    broken: bool = False

    @classmethod
    def text(cls, written: str) -> Written:
        """What a piece of text takes, read once rather than measured again by every line above."""
        return cls(
            width=columns(written),
            last_line=columns(written.rsplit("\n", 1)[-1]),
            broken="\n" in written,
        )

    @classmethod
    def of(cls, width: int) -> Written:
        """A run of `width` columns on one line."""
        return cls(width=width, last_line=width, broken=False)

    def then(self, following: Written) -> Written:
        """What the two take written one after the other."""
        return Written(
            width=self.width + following.width,
            last_line=following.last_line if following.broken else self.last_line + following.last_line,
            broken=self.broken or following.broken,
        )


def render(document: Document, settings: Settings) -> str:
    """Write the document out as the text of a file."""
    return _Layout(settings.column_width, settings.indent).document(document)


def render_with_spans(document: Document, settings: Settings, marker: str) -> tuple[str, list[tuple[int, int]]]:
    """Write the document out, saying which lines hold an entry whose comment carries `marker`.

    A span opens on the entry's own line rather than on the comments above it, which are about
    something else, and closes on its last line, since a value written over several carries the
    marker there.
    """
    layout = _Layout(settings.column_width, settings.indent, marker=marker)
    return layout.document(document), layout.spans


def fits_one_line(entry: Entry, column_width: int, indent: int) -> bool:
    """Whether the entry, written the way the layout writes one, stays on one line that fits."""
    lines = _Layout(column_width, indent).entry(entry)
    return len(lines) == 1 and columns(lines[0]) <= column_width


class _Layout:
    """Lays every line of a document out at the width asked for."""

    def __init__(self, column_width: int, indent: int, marker: str | None = None) -> None:
        self.column_width = column_width
        self.indent = indent
        self.marker = marker
        self.spans: list[tuple[int, int]] = []

    def document(self, document: Document) -> str:
        """The whole file, ending where a line ends whether or not the source did."""
        lines: list[str] = []
        for entry in document.root:
            self._take(lines, entry)
        for section in document.sections:
            lines.extend(section.lead)
            lines.append(self._header(section))
            for entry in section.entries:
                self._take(lines, entry)
        lines.extend(document.trailing)
        return "".join(f"{line}\n" for line in lines)

    def _take(self, lines: list[str], entry: Entry) -> None:
        """Write one entry into the run, noting where it landed when it carries the marker."""
        at = len(lines)
        written = self.entry(entry)
        lines.extend(written)
        if self.marker is not None and entry.comment is not None and self.marker in entry.comment:
            self.spans.append((at + len(entry.lead), len(lines) - 1))

    def _header(self, section: Section) -> str:
        """The `[name]` or `[[name]]` line a section opens with."""
        opening, closing = ("[[", "]]") if section.kind == "array" else ("[", "]")
        header = f"{opening}{render_key(section.name)}{closing}"
        return f"{header}{COMMENT_GAP}{section.comment}" if section.comment else header

    def entry(self, entry: Entry) -> list[str]:
        """One `key = value` line, which a broken value may spread over several."""
        key = render_key(entry.key)
        prefix = columns(key) + len(AROUND_EQUALS)
        # a comment closing the line is part of how wide that line runs
        suffix = columns(entry.comment) + len(COMMENT_GAP) if entry.comment else 0
        written, _ = self.value(entry.value, depth=0, prefix=prefix, suffix=suffix)
        lines = f"{key}{AROUND_EQUALS}{written}".split("\n")
        if entry.comment:
            lines[-1] += f"{COMMENT_GAP}{entry.comment}"
        return [*entry.lead, *lines]

    def value(self, value: Value, depth: int, prefix: int, suffix: int) -> tuple[str, Written]:
        """The text of a value, and how wide it runs."""
        if isinstance(value, Scalar):
            written = normalize_quotes(value)
            return written, Written.text(written)
        if isinstance(value, Array):
            return self.array(value, depth, prefix, suffix)
        return self.inline_table(value, depth, prefix)

    def array(self, array: Array, depth: int, prefix: int, suffix: int) -> tuple[str, Written]:
        """An array, on one line where it fits and broken over lines where it does not."""
        # a comma follows a member wherever the array ends up, so it is part of how wide the line
        # that member closes on runs
        held = [self.value(member.value, depth + 1, self.indent * (depth + 1), 1) for member in array.members]
        texts = [text for text, _ in held]
        widths = [written for _, written in held]
        one_line = _one_line_written(widths)
        if not self._breaks(array, depth, prefix + suffix + one_line.width):
            return _inline(texts), one_line
        # an array too wide on its own is being broken up, which a trailing comma then holds open;
        # one that only overruns because of the key before it is merely wrapped, and a comma there
        # would say something about the file that the file does not say
        outgrew = one_line.width - (2 if array.members else 0) > self.column_width
        was_open = any(member.own_line for member in array.members)
        trailing_comma = array.trailing_comma or (not was_open and outgrew)
        written = self._explode(array, texts, widths, depth, trailing_comma=trailing_comma)
        return written, Written.text(written)

    def inline_table(self, table: InlineTable, depth: int, prefix: int) -> tuple[str, Written]:
        """A `{ ... }` table, which TOML writes on one line.

        One holding a comment keeps the shape the file gave it: no one-line form has anywhere to
        put a comment, and re-laying it out would rob it of what it says.
        """
        if table.raw is not None:
            return table.raw, Written.text(table.raw)
        # members share a line, so each one starts where the ones before it left off
        column = prefix + 2
        texts: list[str] = []
        held: list[Written] = []
        for entry in table.entries:
            key = render_key(entry.key)
            key_width = columns(key) + len(AROUND_EQUALS)
            written, measured = self.value(entry.value, depth, column + key_width, 0)
            column += key_width + measured.last_line + 2
            texts.append(f"{key}{AROUND_EQUALS}{written}")
            held.append(Written.of(key_width).then(measured))
        return _inline(texts, "{", "}"), _one_line_written(held)

    def _breaks(self, array: Array, depth: int, width: int) -> bool:
        """Whether the array is written out over lines rather than closed up onto one.

        A trailing comma, a comment, or a line that would run past `column_width` each force it
        open. An array whose indent already fills the column gains nothing by opening: every line
        it wrote would start past the column it was asked to fit.
        """
        commented = _holds_a_comment(array)
        room = self.indent * (depth + 1) < self.column_width
        return array.trailing_comma or commented or (room and width > self.column_width)

    def _explode(
        self,
        array: Array,
        texts: Sequence[str],
        widths: Sequence[Written],
        depth: int,
        *,
        trailing_comma: bool,
    ) -> str:
        inner, outer = " " * (self.indent * (depth + 1)), " " * (self.indent * depth)
        # each member is measured as it is written, comma included, and the widest sets the column
        # every comment in the array lines up against
        spans = [written.last_line + 1 for written in widths]
        widest = max(spans, default=0)
        last = len(array.members) - 1
        lines = ["["]
        for index, member in enumerate(array.members):
            lines.extend(_lead_lines(member, inner))
            line = f"{inner}{texts[index]}"
            if index < last or trailing_comma:
                line += ","
            if member.comment:
                line += " " * (widest - spans[index] + 1) + member.comment
            lines.append(line)
        lines.extend(_indented(array.trailing, inner))
        lines.append(f"{outer}]")
        return "\n".join(lines)


def _inline(texts: Sequence[str], opening: str = "[", closing: str = "]") -> str:
    """`[ a, b ]`, with a space inside each bracket. An empty one keeps its brackets together."""
    if not texts:
        return f"{opening}{closing}"
    return f"{opening} {', '.join(texts)} {closing}"


def _lead_lines(member: Member, inner: str) -> list[str]:
    """What is written above a member: an empty line the file set it apart with, then comments."""
    comments = [piece for piece in member.lead if piece]
    blank = [""] if _leads_with_blank(member.lead) else []
    return blank + [f"{inner}{comment}" for comment in comments]


def _indented(lead: Sequence[str], inner: str) -> list[str]:
    return [f"{inner}{piece}" if piece else "" for piece in lead]


def _leads_with_blank(lead: Sequence[str]) -> bool:
    """Whether an empty line was written above, before any comment the file put there."""
    return any(not piece for piece in _before_first_comment(lead))


def _before_first_comment(lead: Sequence[str]) -> Sequence[str]:
    for index, piece in enumerate(lead):
        if piece:
            return lead[:index]
    return lead


def _holds_a_comment(array: Array) -> bool:
    """Whether anything the array holds carries a comment, which is what keeps it written out."""
    if any(piece for piece in array.trailing):
        return True
    return any(member.comment or any(piece for piece in member.lead) for member in array.members)


def _one_line_written(held: Sequence[Written]) -> Written:
    """What the members take on one line: a space inside each bracket and a comma between them."""
    last = len(held) - 1
    written = Written.of(1)
    for index, member in enumerate(held):
        written = written.then(Written.of(1)).then(member)
        if index < last:
            written = written.then(Written.of(1))
    return written.then(Written.of(1 if held else 0)).then(Written.of(1))
