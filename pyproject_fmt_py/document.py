"""The document the formatter works on, and how a source is read into it.

The model is flat and line-oriented: a document is the entries written before the first header
followed by the sections each header opens, and a section is the `key = value` lines under it.
Nothing in it says how the file is laid out; `render` decides that from the settings, which is why
a rule can move an entry between tables without touching whitespace.

Comments and blank lines attach to the entry, member or section below them, so reordering carries
them along. Both live in one list, in the order the file wrote them: a comment is its own text,
starting with `#`, and a blank line is the empty string.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Union

import tomlkit
from tomlkit import items as tk
from tomlkit.container import Container
from tomlkit.exceptions import TOMLKitError

from .errors import FormatError

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from .keys import KeyPath

#: What a blank line looks like where trivia is written down.
BLANK = [""]

#: Whether a header opens a table or appends to an array of tables.
SectionKind = Literal["table", "array"]

#: What kind of thing a scalar holds, which decides how it is written back out.
ScalarKind = Literal["string", "integer", "float", "bool", "datetime", "date", "time"]

Value = Union["Scalar", "Array", "InlineTable"]


@dataclass
class Scalar:
    """A value that is one piece of text.

    Attributes:
        kind: What the value is.
        raw: The value exactly as the file wrote it, or None once a rule has rewritten it.
        text: The text a string holds, decoded. Empty for everything else.
    """

    kind: ScalarKind
    raw: str | None = None
    text: str = ""

    @classmethod
    def of_string(cls, text: str) -> Scalar:
        """A string value the formatter built, to be written in whatever form suits it."""
        return cls(kind="string", raw=None, text=text)

    def replace_text(self, text: str) -> None:
        """Give a string a new value, dropping the spelling the file used for the old one."""
        self.text = text
        self.raw = None


@dataclass
class Member:
    """One value of an array, with the comments written above and beside it.

    Attributes:
        value: What the member holds.
        lead: The comments and blank lines written above it.
        comment: The comment closing its line.
        own_line: Whether the source gave the member a line of its own, which is what tells an
            array the file already opened from one this formatter is breaking up.
    """

    value: Value
    lead: list[str] = field(default_factory=list)
    comment: str | None = None
    own_line: bool = False


@dataclass
class Array:
    """An array of values.

    Attributes:
        members: What the array holds, in order.
        trailing_comma: Whether the source closed the last member with a comma, which keeps the
            array written across lines however short it is.
        trailing: The comments and blank lines below the last member, above the closing bracket.
    """

    members: list[Member] = field(default_factory=list)
    trailing_comma: bool = False
    trailing: list[str] = field(default_factory=list)


@dataclass
class InlineTable:
    """A `{ ... }` table, whose entries TOML writes on one line.

    Attributes:
        entries: What the table holds, each with the comments written around it.
        trailing: The comments below the last member, above the closing brace.
        raw: The table exactly as the file wrote it, where it wrote one holding a comment. No
            one-line form can keep a comment, so such a table is left as it stands rather than
            re-laid out and robbed of what it says.
    """

    entries: list[Entry] = field(default_factory=list)
    trailing: list[str] = field(default_factory=list)
    raw: str | None = None


@dataclass
class Entry:
    """One `key = value` line, with the comments written above and beside it.

    The key is the whole path the line writes, so `a.b = 1` is one entry of two segments rather
    than a table holding another.
    """

    key: KeyPath
    value: Value
    lead: list[str] = field(default_factory=list)
    comment: str | None = None


@dataclass
class Section:
    """What one `[name]` or `[[name]]` header opens."""

    name: KeyPath
    kind: SectionKind = "table"
    entries: list[Entry] = field(default_factory=list)
    lead: list[str] = field(default_factory=list)
    comment: str | None = None


@dataclass
class Document:
    """A whole `pyproject.toml`.

    Attributes:
        root: The entries written before the first header.
        sections: Every header the file opens, in the order it wrote them.
        trailing: The comments after the last entry, which nothing sits below.
    """

    root: list[Entry] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    trailing: list[str] = field(default_factory=list)

    def entries(self) -> Iterator[tuple[KeyPath, Entry]]:
        """Every entry in the document, with the name of the table it sits in."""
        for entry in self.root:
            yield (), entry
        for section in self.sections:
            for entry in section.entries:
                yield section.name, entry

    def sections_named(self, name: KeyPath) -> list[Section]:
        """The sections written under `name`, in document order.

        An array of tables repeats its header, so a name can name several sections.
        """
        return [section for section in self.sections if section.name == name]


def parse(content: str) -> Document:
    """Read a source into a document.

    Args:
        content: The text of the file.

    Returns:
        What the file says, with its comments attached to what they sit above.

    Raises:
        FormatError: If the text is not a TOML document.
    """
    try:
        parsed = tomlkit.parse(content)
    except TOMLKitError as exc:
        raise FormatError(str(exc)) from exc
    return _Reader().read(parsed)


def parse_repeating(content: str) -> Document:
    """`parse`, for a source that may say the same name twice.

    Turning a disabled key back on can put a name in the document twice, which no reader accepts.
    The formatter walks what the file wrote in the order it wrote it, so the repeat is kept where
    the reader lists what it read and left out of the index it looks names up in.

    Raises:
        FormatError: If the text is not a TOML document for some other reason.
    """
    with _repeats_allowed():
        return parse(content)


@contextlib.contextmanager
def _repeats_allowed() -> Iterator[None]:
    """Let the reader list a name it has already listed, rather than refusing the document."""
    appended, raw_appended = Container.append, Container._raw_append  # noqa: SLF001

    def keep(self: Container, key: tk.Key | str | None, item: tk.Item) -> None:
        self._body.append((tk.SingleKey(key) if isinstance(key, str) else key, item))

    def append(self: Container, key: tk.Key | str | None, item: tk.Item, validate: bool = True) -> Container:  # noqa: FBT001, FBT002
        try:
            return appended(self, key, item, validate=validate)
        except TOMLKitError:
            keep(self, key, item)
            return self

    def raw_append(self: Container, key: tk.Key | None, item: tk.Item) -> None:
        try:
            raw_appended(self, key, item)
        except TOMLKitError:
            keep(self, key, item)

    Container.append = append  # type: ignore[method-assign, assignment]
    Container._raw_append = raw_append  # type: ignore[method-assign]  # noqa: SLF001
    try:
        yield
    finally:
        Container.append = appended  # type: ignore[method-assign]
        Container._raw_append = raw_appended  # type: ignore[method-assign]  # noqa: SLF001


class _Reader:
    """Flattens the tree tomlkit builds back into the lines the file wrote."""

    def __init__(self) -> None:
        self.document = Document()
        self.pending: list[str] = []
        self.target: list[Entry] = self.document.root

    def read(self, container: Container) -> Document:
        """Walk a parsed source and hand back the document it describes."""
        self._container(container, ())
        self.document.trailing = self.pending
        return self.document

    def _take_lead(self) -> list[str]:
        lead, self.pending = self.pending, []
        return lead

    def _container(self, container: Container, prefix: KeyPath) -> None:
        for key, item in container.body:
            if isinstance(item, tk.Comment):
                self.pending.append(_comment_text(item))
            elif isinstance(item, tk.Whitespace):
                self.pending.extend(BLANK * item.as_string().count("\n"))
            elif key is None:
                continue
            elif isinstance(item, tk.AoT):
                self._array_of_tables(key, item, prefix)
            elif isinstance(item, tk.Table) and not key.is_dotted():
                self._table(key, item, prefix)
            else:
                self.target.append(self._entry(key, item, ()))

    def _table(self, key: tk.Key, table: tk.Table, prefix: KeyPath) -> None:
        name = (*prefix, key.key)
        if table.is_super_table():
            # `[a.b]` with no `[a]` of its own: the parent is a place to hang the child, not a line
            self._container(table.value, name)
            return
        self._open(name, "table", table)
        self._container(table.value, name)

    def _array_of_tables(self, key: tk.Key, aot: tk.AoT, prefix: KeyPath) -> None:
        name = (*prefix, key.key)
        for table in aot.body:
            self._open(name, "array", table)
            self._container(table.value, name)

    def _open(self, name: KeyPath, kind: SectionKind, table: tk.Table) -> None:
        section = Section(name=name, kind=kind, lead=self._take_lead(), comment=_trailing(table))
        self.document.sections.append(section)
        self.target = section.entries

    def _entry(self, key: tk.Key, item: tk.Item, prefix: KeyPath) -> Entry:
        lead = self._take_lead()
        path, leaf = _walk_dotted(key, item, prefix)
        return Entry(key=path, value=read_value(leaf), lead=lead, comment=_trailing(leaf))


def _walk_dotted(key: tk.Key, item: tk.Item, prefix: KeyPath) -> tuple[KeyPath, tk.Item]:
    """Follow `a.b.c = 1` down to the value, collecting the segments on the way."""
    path = (*prefix, key.key)
    while key.is_dotted() and isinstance(item, tk.Table):
        key, item = _named(item.value)[0]
        path = (*path, key.key)
    return path, item


def read_value(item: tk.Item) -> Value:
    """The value an item holds, in the form the formatter works on."""
    if isinstance(item, tk.Array):
        return _array(item)
    if isinstance(item, tk.InlineTable):
        return _inline_table(item)
    if isinstance(item, tk.String):
        return Scalar(kind="string", raw=item.as_string(), text=str(item))
    return Scalar(kind=_kind_of(item), raw=item.as_string())


def _inline_table(item: tk.InlineTable) -> InlineTable:
    """What a `{ ... }` table holds, with the comments the file wrote around its members."""
    entries: list[Entry] = []
    lead: list[str] = []
    on_the_same_line = False
    for key, held in item.value.body:
        if isinstance(held, tk.Whitespace):
            if "\n" in held.as_string():
                on_the_same_line = False
            continue
        if isinstance(held, tk.Comment):
            text = held.trivia.comment.strip()
            # a comment past the last value on its line closes that value's line
            if on_the_same_line and entries:
                entries[-1].comment = text
            else:
                lead.append(text)
            continue
        if key is None:  # pragma: no cover - a value inside a table carries a key
            continue
        entry = _inline_entry(key, held)
        entry.lead = lead
        lead = []
        entries.append(entry)
        on_the_same_line = True
    return InlineTable(entries=entries, trailing=lead, raw=_written_with_a_comment(item))


def _written_with_a_comment(item: tk.InlineTable) -> str | None:
    """The table as the file wrote it, where what it wrote holds a comment."""
    written = item.as_string()
    return written if written and _holds_a_comment(written) else None


def _holds_a_comment(written: str) -> bool:
    """Whether the text writes a `#` where a comment stands rather than inside a string."""
    quote: str | None = None
    at = 0
    while at < len(written):
        held = written[at]
        if quote is not None:
            if held == "\\":
                at += 2
                continue
            if held == quote:
                quote = None
        elif held in "\"'":
            quote = held
        elif held == "#":
            return True
        at += 1
    return False


def _inline_entry(key: tk.Key, item: tk.Item) -> Entry:
    path, leaf = _walk_dotted(key, item, ())
    return Entry(key=path, value=read_value(leaf))


def _array(array: tk.Array) -> Array:
    members: list[Member] = []
    lead: list[str] = []
    trailing_comma = False
    for group in array._value:  # noqa: SLF001 - the only way to reach an array's own comments
        lead.extend(BLANK * _blanks_before(group.indent))
        own_line = "\n" in (group.indent.as_string() if group.indent is not None else "")
        value, comment = group.value, _comment_of(group)
        if value is None or isinstance(value, tk.Null):
            if comment:  # a comment on its own line belongs to whatever comes below it
                lead.append(comment)
            continue
        members.append(Member(value=read_value(value), lead=lead, comment=comment, own_line=own_line))
        lead = []
        trailing_comma = group.comma is not None
    # what is left sits below the last member, with nothing under it but the closing bracket
    return Array(members=members, trailing_comma=trailing_comma, trailing=lead)


def _blanks_before(indent: tk.Whitespace | None) -> int:
    """How many empty lines a member's leading whitespace holds, its own line break aside."""
    return max(indent.as_string().count("\n") - 1, 0) if indent is not None else 0


def _kind_of(item: tk.Item) -> ScalarKind:
    for kind, held in (
        ("bool", tk.Bool),
        ("integer", tk.Integer),
        ("float", tk.Float),
        ("datetime", tk.DateTime),
        ("date", tk.Date),
        ("time", tk.Time),
    ):
        if isinstance(item, held):
            return kind  # type: ignore[return-value]
    return "string"


def _named(container: Container) -> list[tuple[tk.Key, tk.Item]]:
    """The entries of a container that carry a key, dropping the trivia between them."""
    return [(key, item) for key, item in container.body if key is not None and not isinstance(item, tk.Whitespace)]


def _comment_text(item: tk.Item) -> str:
    return item.trivia.comment.strip()


def _trailing(item: tk.Item) -> str | None:
    comment = item.trivia.comment.strip()
    return comment or None


def _comment_of(group: object) -> str | None:
    comment = getattr(group, "comment", None)
    if comment is None:
        return None
    return str(comment.trivia.comment).strip() or None


def iter_values(value: Value) -> Iterator[Value]:
    """A value and everything written inside it."""
    yield value
    if isinstance(value, Array):
        for member in value.members:
            yield from iter_values(member.value)
    elif isinstance(value, InlineTable):
        for entry in value.entries:
            yield from iter_values(entry.value)


def strings_in(value: Value) -> Iterator[Scalar]:
    """Every string written inside a value, including the value itself."""
    for held in iter_values(value):
        if isinstance(held, Scalar) and held.kind == "string":
            yield held


def entries_named(entries: Iterable[Entry], key: str) -> Iterator[Entry]:
    """The entries whose path starts with `key`."""
    for entry in entries:
        if entry.key and entry.key[0] == key:
            yield entry
