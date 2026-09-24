"""Read and write the golden corpus files under `tests/data/corpus`.

A case is one file holding the source and what the formatter is expected to write for it under
each profile in `profiles.py`::

    %%% case foo_tests.rs::test_bar
    %%% input -
    [project]
    name = "x"
    %%% output short
    [project]
    name = "x"
    %%% error long
    project.version is invalid

Sections are delimited by lines starting with `%%% `, so no line of a case body may start with
that; `dumps` refuses to write one that does. A body that does not end in a newline carries a
`no-eol` flag on its own header line, since the file itself always ends in one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

DELIMITER = "%%% "
_NO_EOL = "no-eol"


@dataclass
class Case:
    """One source document and what each profile should make of it."""

    name: str
    origin: str
    source: str
    #: Profile name -> formatted output.
    outputs: dict[str, str] = field(default_factory=dict)
    #: Profile name -> the message the formatter rejected the source with.
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def profiles(self) -> list[str]:
        """Every profile the case records an outcome for, in file order."""
        return [*self.outputs, *self.errors]


def dumps(case: Case) -> str:
    """Render a case as the text of its corpus file."""
    parts = [f"{DELIMITER}case {case.origin}\n", *_section("input", "-", case.source, case.name)]
    for profile, text in case.outputs.items():
        parts.extend(_section("output", profile, text, case.name))
    for profile, message in case.errors.items():
        parts.extend(_section("error", profile, message + "\n", case.name))
    return "".join(parts)


def loads(text: str, name: str) -> Case:
    """Read a case back out of the text of its corpus file."""
    case = Case(name=name, origin="", source="")
    head: list[str] = []
    lines: list[str] = []

    def close() -> None:
        if not head:
            return
        kind, profile, *flags = head
        body = "".join(lines)
        if _NO_EOL in flags:
            body = body[:-1]
        if kind == "input":
            case.source = body
        elif kind == "output":
            case.outputs[profile] = body
        else:
            case.errors[profile] = body.rstrip("\n")

    for line in text.splitlines(keepends=True):
        if line.startswith(DELIMITER):
            kind, _, rest = line[len(DELIMITER) :].strip().partition(" ")
            if kind == "case":
                case.origin = rest
                continue
            close()
            head, lines = [kind, *rest.split()], []
        else:
            lines.append(line)
    close()
    return case


def load_all(root: Path) -> list[Case]:
    """Every case under `root`, named by its path relative to it without the suffix."""
    return [loads(path.read_text(encoding="utf-8"), _name(path, root)) for path in sorted(root.rglob("*.txt"))]


def path_of(root: Path, name: str) -> Path:
    """Where the case called `name` is stored under `root`."""
    return root.joinpath(*name.split("/")).with_suffix(".txt")


def _name(path: Path, root: Path) -> str:
    return path.relative_to(root).with_suffix("").as_posix()


def _section(kind: str, profile: str, body: str, name: str) -> list[str]:
    for line in body.splitlines():
        if line.startswith(DELIMITER):
            msg = f"{name}: a case body cannot hold a line starting with {DELIMITER!r}"
            raise ValueError(msg)
    head = f"{DELIMITER}{kind} {profile}"
    if body and not body.endswith("\n"):
        return [f"{head} {_NO_EOL}\n", body + "\n"]
    return [f"{head}\n", body]
