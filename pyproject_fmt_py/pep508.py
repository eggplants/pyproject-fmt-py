"""Reading and writing a dependency the way PEP 508 spells one.

A requirement this cannot read is left as the file wrote it, so nothing the file says is dropped by
reading only the part that parses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .pep440 import Version

#: What a name writes between its words, all of which compare alike.
_SEPARATORS = re.compile(r"[-_.]+")

#: The operators a clause of a specifier set opens with, longest first so `===` beats `==`.
OPERATORS: tuple[str, ...] = ("===", "~=", "==", ">=", ">", "<=", "<", "!=")

#: What a marker compares with, from the dependency specifier grammar.
MARKER_OPERATORS = frozenset({"==", "!=", "<", "<=", ">", ">=", "~=", "==="})

#: The environment a marker may name. Anything else on that side is a value, which is quoted.
MARKER_VARIABLES = frozenset(
    {
        "os_name",
        "sys_platform",
        "platform_machine",
        "platform_python_implementation",
        "platform_release",
        "platform_system",
        "platform_version",
        "python_version",
        "python_full_version",
        "implementation_name",
        "implementation_version",
        "extra",
        "dependency_groups",
    }
)

#: The characters `===` compares the text of, which is anything a version token may hold.
_ARBITRARY = re.compile(r"[A-Za-z0-9\-_.*+!]+")


def names_a_distribution(name: str) -> bool:
    """Whether the text names a distribution the way PEP 508 spells one."""
    return bool(name) and name[0].isalnum() and name[-1].isalnum() and all(_is_name_character(held) for held in name)


def canonical_name_of(name: str) -> str:
    """The canonical spelling of a distribution name.

    Raises:
        ValueError: If the text does not name a distribution.
    """
    held = name.strip()
    if not names_a_distribution(held):
        msg = f"Invalid name '{held}'"
        raise ValueError(msg)
    return _SEPARATORS.sub("-", held.lower())


@dataclass
class VersionOp:
    """One clause of a specifier set: an operator and what it compares against."""

    op: str
    literal: str
    version: Version | None = None

    @classmethod
    def parse(cls, spec: str) -> VersionOp:
        """Read one clause.

        Raises:
            ValueError: If the text is not a clause PEP 440 puts together.
        """
        text = spec.strip()
        op = next((held for held in OPERATORS if text.startswith(held)), None)
        if op is None:
            msg = f"Invalid operator: {text}"
            raise ValueError(msg)
        literal = text[len(op) :].strip()
        if not literal:
            msg = f"The clause names no version: '{spec}'"
            raise ValueError(msg)
        # `===` compares the text it is given, which is anything the version token may hold
        if op == "===":
            if not _ARBITRARY.fullmatch(literal):
                msg = f"The version is written outside its own characters: '{literal}'"
                raise ValueError(msg)
            try:
                return cls(op=op, literal=literal, version=Version.parse(literal))
            except ValueError:
                return cls(op=op, literal=literal)
        version = Version.parse(literal)
        _holds_together(op, version)
        return cls(op=op, literal=literal, version=version)

    def __str__(self) -> str:
        """The clause as PEP 440 spells one."""
        # `===` compares the text it was given, so that is what is written back
        if self.version is not None and self.op != "===":
            return f"{self.op}{self.version}"
        return f"{self.op}{self.literal}"


def _holds_together(op: str, version: Version) -> None:
    """Check that PEP 440 puts this operator and this operand together.

    Raises:
        ValueError: With what the pair says that PEP 440 does not.
    """
    if version.has_wildcard:
        if op not in {"==", "!="}:
            msg = f"`{op}` names no version ending in `.*`"
            raise ValueError(msg)
        # a wildcard stands for the numbers a release goes on to name, and these say none
        if version.pre or version.post or version.dev or version.local:
            msg = "`.*` follows the release numbers alone"
            raise ValueError(msg)
    # a local version says which build of a release it is, which only `==` and `!=` read
    if version.local is not None and op not in {"==", "!="}:
        msg = f"`{op}` names no local version"
        raise ValueError(msg)
    # a compatible release names the version it holds the last number of open
    if op == "~=" and len(version.release) < 2:  # noqa: PLR2004 - two is what `~=` leaves open
        msg = f"`{op}` names a version of at least two numbers"
        raise ValueError(msg)


@dataclass(frozen=True)
class Marker:
    """An environment marker, as the tree PEP 508 reads it as."""

    kind: str  # "and" | "or" | "compare" | "paren"
    parts: tuple[Marker, ...] = ()
    left: str = ""
    op: str = ""
    right: str = ""

    @classmethod
    def parse(cls, text: str) -> Marker:
        """Read a marker.

        Raises:
            ValueError: If the text is not a marker PEP 508 reads.
        """
        parser = _MarkerParser(_tokenize(text))
        held = parser.marker()
        if parser.peek() is not None:
            msg = "Unexpected trailing tokens"
            raise ValueError(msg)
        return held

    def __str__(self) -> str:
        """The marker in its canonical spelling."""
        if self.kind in {"and", "or"}:
            return f" {self.kind} ".join(str(part) for part in self.parts)
        if self.kind == "paren":
            return f"({self.parts[0]})"
        right = _quoted(self.right)
        if self.op in {"in", "not in"}:
            return f"{self.left} {self.op} {right}"
        return f"{self.left}{self.op}{right}"


def _quoted(operand: str) -> str:
    """A value written with the quote that does not close it, since PEP 508 has no escape."""
    if len(operand) >= 2 and operand[0] == operand[-1] and operand[0] in "\"'":  # noqa: PLR2004 - a quote either side
        inside = operand[1:-1]
        return f'"{inside}"' if "'" in inside else f"'{inside}'"
    return operand


@dataclass
class Requirement:
    """What a dependency names: a distribution, its extras, its versions or URL, and its marker."""

    name: str
    extras: list[str] = field(default_factory=list)
    specifiers: list[VersionOp] = field(default_factory=list)
    url: str | None = None
    marker: Marker | None = None

    @classmethod
    def parse(cls, raw: str) -> Requirement:
        """Read a dependency.

        Raises:
            ValueError: With why the text is not one this reads.
        """
        # a dependency is written on one line, so a break inside it is text no reader accepts
        if "\n" in raw or "\r" in raw:
            msg = "A requirement is written on one line"
            raise ValueError(msg)
        at = _marker_break(raw)
        head, marker_text = (raw[:at], raw[at + 1 :]) if at is not None else (raw, None)
        url_at = head.find("@")
        before_url = head[:url_at] if url_at != -1 else head

        name, extras, constraints = _read_name(before_url)
        url: str | None = None
        specifiers: list[VersionOp] = []
        if url_at != -1:
            # a dependency names a version or a direct reference, never both
            if constraints:
                msg = f"The requirement names a version and a URL: '{raw}'"
                raise ValueError(msg)
            url = head[url_at + 1 :].strip()
            # a URL holds no whitespace, so what follows one is text this cannot read
            if not url:
                msg = "The direct reference names no URL"
                raise ValueError(msg)
            if any(held.isspace() for held in url):
                msg = f"Unexpected text after the URL: '{url}'"
                raise ValueError(msg)
        elif constraints:
            specifiers = _read_specifiers(constraints)

        marker = None
        if marker_text is not None:
            try:
                marker = Marker.parse(marker_text.strip())
            except ValueError as exc:
                msg = f"Invalid marker: {exc}"
                raise ValueError(msg) from exc
        return cls(name=name, extras=extras, specifiers=specifiers, url=url, marker=marker)

    @property
    def canonical_name(self) -> str:
        """The name with its case and its separators settled."""
        return _SEPARATORS.sub("-", self.name.lower())

    @property
    def is_name_only(self) -> bool:
        """Whether the requirement names a distribution and nothing else about it."""
        return not self.extras and not self.specifiers and self.url is None and self.marker is None

    def normalize(self, *, keep_full_version: bool) -> Requirement:
        """Settle the name's spelling and, unless asked otherwise, drop redundant `.0` suffixes."""
        self.name = self.canonical_name
        if keep_full_version:
            return self
        for held in self.specifiers:
            # `~=` says what it says by the numbers it names, and `===` compares the text it was
            # given; a trailing `.0` is only redundant without pre/post/dev/local segments
            if held.op in {"~=", "==="} or held.version is None:
                continue
            version = held.version
            if version.has_wildcard or version.pre or version.post or version.dev or version.local:
                continue
            version.drop_redundant_zeros()
        return self

    def __str__(self) -> str:
        """The requirement as PEP 508 spells one, with its extras and versions in order."""
        written = self.name
        if self.extras:
            written += "[" + ",".join(sorted(self.extras)) + "]"
        if self.url is not None:
            written += f" @ {self.url}"
        else:
            written += ",".join(str(held) for held in self.specifiers)
        if self.marker is not None:
            # PEP 508 asks for whitespace after a URL, or the `;` reads as part of the URI
            written += " ; " if self.url is not None else "; "
            written += str(self.marker)
        return written


def _marker_break(raw: str) -> int | None:
    """Where the semicolon that opens an environment marker sits.

    A URL holds no whitespace and may hold a semicolon of its own, so what separates a direct
    reference from its marker is the space PEP 508 writes before it.
    """
    for at, held in enumerate(raw):
        if held == ";" and ("@" not in raw[:at] or (raw[:at] and raw[at - 1].isspace())):
            return at
    return None


def _read_name(text: str) -> tuple[str, list[str], str]:
    """The distribution, its extras and whatever follows them.

    Raises:
        ValueError: If the text does not open with a name, or its extras do not close.
    """
    start = text.find("[")
    if start != -1:
        end = text.find("]", start)
        if end == -1:
            msg = "Unclosed extras bracket"
            raise ValueError(msg)
        inside = text[start + 1 : end].strip()
        extras = [extra.strip() for extra in inside.split(",")] if inside else []
        # an extra names a distribution, so text that does not is text this cannot read
        if not all(names_a_distribution(extra) for extra in extras):
            msg = f"Invalid extras: '{text[start : end + 1]}'"
            raise ValueError(msg)
        name, constraints = text[:start], text[end + 1 :].strip()
    else:
        name_end = next((at for at, held in enumerate(text) if held in "=!<>~("), len(text))
        name, extras, constraints = text[:name_end], [], text[name_end:].strip()
    if not names_a_distribution(name.strip()):
        msg = f"Invalid name '{name.strip()}'"
        raise ValueError(msg)
    return name.strip(), extras, constraints


def _read_specifiers(text: str) -> list[VersionOp]:
    """The clauses a requirement names, with the parentheses PEP 508 allows around them.

    Raises:
        ValueError: If the text is not a specifier set.
    """
    inside = text
    if inside.startswith("("):
        if not inside.endswith(")"):
            msg = f"Unclosed parenthesis: '{text}'"
            raise ValueError(msg)
        inside = inside[1:-1].strip()
    # a list may close with a comma, which names no clause of its own
    if inside.endswith(","):
        inside = inside[:-1].rstrip()
    if not inside or "(" in inside or ")" in inside:
        msg = f"The requirement names no version: '{text}'"
        raise ValueError(msg)
    held = []
    for spec in inside.split(","):
        try:
            held.append(VersionOp.parse(spec))
        except ValueError as exc:
            msg = f"Invalid version specifier '{spec}': {exc}"
            raise ValueError(msg) from exc
    return held


def _is_name_character(held: str) -> bool:
    return held.isascii() and (held.isalnum() or held in "._-")


class _Token:
    """One piece of a marker, read out of the text it was written in."""

    __slots__ = ("kind", "text")

    def __init__(self, kind: str, text: str) -> None:
        self.kind, self.text = kind, text


def _tokenize(text: str) -> list[_Token]:
    """The pieces a marker is written out of.

    Raises:
        ValueError: If the text holds something no marker does.
    """
    tokens: list[_Token] = []
    at = 0
    while at < len(text):
        held = text[at]
        if held in " \t":
            at += 1
        elif held in "()":
            tokens.append(_Token("(" if held == "(" else ")", held))
            at += 1
        elif held in "=!><~":
            end = _run_end(text, at, "=<>!~")
            tokens.append(_Token("op", text[at:end]))
            at = end
        elif held in "\"'":
            close = text.find(held, at + 1)
            if close == -1:
                msg = "Unclosed string literal"
                raise ValueError(msg)
            tokens.append(_Token("string", text[at : close + 1]))
            at = close + 1
        elif held.isascii() and (held.isalpha() or held == "_"):
            end = _run_end(text, at, None)
            word = text[at:end]
            tokens.append(_Token(word if word in {"and", "or"} else "ident", word))
            at = end
        else:
            msg = f"Unexpected character: {held}"
            raise ValueError(msg)
    return tokens


def _run_end(text: str, at: int, held: str | None) -> int:
    end = at
    while end < len(text):
        character = text[end]
        allowed = (
            character in held
            if held is not None
            else (character.isascii() and (character.isalnum() or character == "_"))
        )
        if not allowed:
            break
        end += 1
    return end


class _MarkerParser:
    """Reads the tree a marker's tokens describe."""

    def __init__(self, tokens: list[_Token]) -> None:
        self.tokens = tokens
        self.at = 0

    def peek(self) -> _Token | None:
        """The token the parser is on, or None where it has read them all."""
        return self.tokens[self.at] if self.at < len(self.tokens) else None

    def take(self) -> _Token | None:
        """The token the parser is on, moving past it."""
        held = self.peek()
        if held is not None:
            self.at += 1
        return held

    def marker(self) -> Marker:
        """The whole marker."""
        return self._joined("or", self._and)

    def _and(self) -> Marker:
        return self._joined("and", self._atom)

    def _joined(self, kind: str, below) -> Marker:  # noqa: ANN001 - the parser's own next level
        parts = [below()]
        while (held := self.peek()) is not None and held.kind == kind:
            self.take()
            parts.append(below())
        return parts[0] if len(parts) == 1 else Marker(kind=kind, parts=tuple(parts))

    def _atom(self) -> Marker:
        held = self.peek()
        if held is not None and held.kind == "(":
            self.take()
            inside = self.marker()
            closing = self.take()
            if closing is None or closing.kind != ")":
                msg = "Expected ')'"
                raise ValueError(msg)
            return Marker(kind="paren", parts=(inside,))
        return self._comparison()

    def _comparison(self) -> Marker:
        left = self._operand()
        op = self._operator()
        right = self._operand()
        return Marker(kind="compare", left=left, op=op, right=right)

    def _operator(self) -> str:
        held = self.take()
        if held is None:
            msg = "Expected operator"
            raise ValueError(msg)
        if held.kind == "op":
            # PEP 508 names the operators a marker compares with, and nothing else is one
            if held.text not in MARKER_OPERATORS:
                msg = f"`{held.text}` is no marker operator"
                raise ValueError(msg)
            return held.text
        if held.kind == "ident" and held.text == "in":
            return "in"
        if held.kind == "ident" and held.text == "not":
            following = self.take()
            if following is None or following.text != "in":
                msg = "Expected 'in' after 'not'"
                raise ValueError(msg)
            return "not in"
        msg = "Expected operator"
        raise ValueError(msg)

    def _operand(self) -> str:
        held = self.take()
        if held is None:
            msg = "Expected a quoted value or a marker variable"
            raise ValueError(msg)
        if held.kind == "string":
            return held.text
        if held.kind == "ident":
            if held.text not in MARKER_VARIABLES:
                msg = f"`{held.text}` is no marker variable, and a value is quoted"
                raise ValueError(msg)
            return held.text
        msg = "Expected a quoted value or a marker variable"
        raise ValueError(msg)
