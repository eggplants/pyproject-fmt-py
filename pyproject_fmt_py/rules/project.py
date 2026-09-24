"""The PEP 621 core metadata table.

Keys follow the canonical metadata order. The name, the dependency arrays, the classifiers and the
keywords are normalized, and the version is validated: a value PEP 440 does not read is reported
and the file left as it was.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from packaging.licenses import InvalidLicenseExpression, canonicalize_license_expression

from ..arrays import dedupe_strings_in, map_strings, sort, sort_names_in, text_of
from ..disabled import is_enabled_here
from ..document import Array, Entry, InlineTable, Member, Scalar, Section
from ..errors import FormatError
from ..keys import dotted_name
from ..nesting import Width, collapse_array_of_tables
from ..pep440 import is_valid_version
from ..pep508 import canonical_name_of, names_a_distribution
from ..sections import active_entries, for_keys_under, reorder_under
from ..sorting import natural_lexical_key
from . import classifiers as classifier_rules
from ._data import PROJECT_KEY_ORDER as KEY_ORDER
from .build_system import normalized, sort_name

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..config import TableShape
    from ..document import Document, Value
    from ..keys import KeyPath

PATH: KeyPath = ("project",)

#: A person is read name first, whichever form the file wrote them in.
PEOPLE_KEY_ORDER = ("name", "email")

#: The words an SPDX expression joins its identifiers with.
_OPERATORS = frozenset({"and", "or", "with"})

#: A space before a full stop that closes a sentence, which the description writes without one.
_LOOSE_STOP = re.compile(r" \.(\W)")

_SEPARATORS = re.compile(r"[-_.]+")


def fix(  # noqa: PLR0913 - the table reads every setting that says anything about it
    document: Document,
    *,
    keep_full_version: bool,
    max_supported_python: tuple[int, int],
    min_supported_python: tuple[int, int],
    generate_python_version_classifiers: bool,
    table_shape: TableShape,
) -> None:
    """Normalize every field the table holds and put its keys in order.

    Raises:
        FormatError: If `project.version` is not a version PEP 440 reads.
    """
    for people in ("authors", "maintainers"):
        name = (*PATH, people)
        if table_shape.should_collapse(name):
            collapse_array_of_tables(document, name, Width.unbounded())
        else:
            _expand_array_of_tables(document, name)
        # whichever form the file is left in, a person reads name first
        _order_array_elements(document, name, PEOPLE_KEY_ORDER)

    _expand_entry_points(document)

    invalid_version: list[str] = []

    def visit(key: str, value: Value) -> None:
        _normalize_field(_dispatch_on(key), value, keep_full_version=keep_full_version, invalid=invalid_version)

    for_keys_under(document, PATH, visit)
    if invalid_version:
        msg = f"project.version `{invalid_version[0]}` is not a valid PEP 440 version"
        raise FormatError(msg)

    _generate_classifiers(
        document,
        max_supported_python=max_supported_python,
        min_supported_python=min_supported_python,
        wanted=generate_python_version_classifiers,
    )
    for_keys_under(document, PATH, _sort_classifiers)
    _normalize_extra_names(document)
    reorder_under(document, PATH, KEY_ORDER)


def _dispatch_on(key: str) -> str:
    """What a rule reads a key by: its first segment, except where it names something else.

    The deprecated `license.file` and `license.text` hold a path and the license text itself,
    neither of which is an SPDX expression.
    """
    return "" if key in {"license.file", "license.text"} else key.split(".", 1)[0]


def _normalize_field(key: str, value: Value, *, keep_full_version: bool, invalid: list[str]) -> None:
    rewrite = _REWRITTEN.get(key)
    if rewrite is not None:
        _update(value, rewrite)
    elif key == "version":
        text = _text_of(value)
        if text is not None and not is_valid_version(text):
            invalid.append(text)
    elif key in {"dependencies", "optional-dependencies"}:
        _normalize_and_sort_requirements(value, keep_full_version=keep_full_version)
    elif key == "dynamic":
        sort_names_in(value)
    elif key == "keywords":
        dedupe_strings_in(value, str.lower)
        sort_names_in(value)
    elif key in {"import-names", "import-namespaces"}:
        map_strings(value, lambda text: _import_name(text) or text)
        sort_names_in(value)
    elif key == "classifiers":
        _sort_classifiers(key, value)


def _sort_classifiers(key: str, value: Value) -> None:
    """A classifier is one of a fixed set of strings, so case tells a bad spelling from the claim."""
    if key == "classifiers":
        dedupe_strings_in(value)
        sort_names_in(value)


def _normalize_and_sort_requirements(value: Value, *, keep_full_version: bool) -> None:
    """Requirements sort by the name they install, and by the whole line when two share a name."""
    if not isinstance(value, Array):
        return
    map_strings(value, lambda text: normalized(text, keep_full_version=keep_full_version))
    sort(value, _requirement_key)


def _requirement_key(member: Member) -> tuple[object, object] | None:
    text = text_of(member)
    if text is None:
        return None
    return natural_lexical_key(sort_name(text)), natural_lexical_key(text)


def _canonical_or_written(text: str) -> str:
    try:
        return canonical_name_of(text)
    except ValueError:
        return text


def _spelled_license(text: str) -> str:
    """Uppercase the words an SPDX expression joins with, and leave prose as the file wrote it.

    There is no telling prose from an expression by shape alone: `MIT or later` is shaped like one
    and names no license, so the text is only rewritten once it parses as an expression over
    registered identifiers.
    """
    if not _names_a_license(text):
        return text
    return " ".join(word.upper() if word.lower() in _OPERATORS else word for word in text.split())


def _names_a_license(text: str) -> bool:
    try:
        canonicalize_license_expression(text)
    except (InvalidLicenseExpression, ValueError):
        return False
    return True


def _one_run_of_words(text: str) -> str:
    """The description read as one run of words: a line break says what a space says."""
    return _LOOSE_STOP.sub(r".\1", " ".join(text.split()))


def _tightened_range(text: str) -> str:
    """Whitespace between the clauses says nothing, while whitespace inside one is what makes the
    text something PEP 440 does not read: taking it out would name a constraint the file does not.
    """
    return "".join(text.split()) if classifier_rules.read_specifiers(text) is not None else text


def _import_name(text: str) -> str | None:
    """The canonical spelling of an import name, or None where the text is not one.

    PEP 794 writes a dotted name of Python identifiers, and lets one modifier follow it: the word
    `private`. Text that says anything else is left alone.
    """
    name, _, rest = text.partition(";")
    modifier = rest.strip() if ";" in text else None
    name = name.strip()
    if not name or not all(_is_an_identifier(segment) for segment in name.split(".")):
        return None
    if modifier is None:
        return name
    return f"{name}; private" if modifier == "private" else None


def _is_an_identifier(segment: str) -> bool:
    return segment.isidentifier()


#: The fields whose value is one string this rewrites in place.
_REWRITTEN: dict[str, Callable[[str], str]] = {
    # the project's name is one distribution name, not a dependency: text that names anything else
    # is left as the file wrote it
    "name": _canonical_or_written,
    "license": _spelled_license,
    "description": _one_run_of_words,
    "requires-python": _tightened_range,
}


def _update(value: Value, rewrite: Callable[[str], str]) -> None:
    """Rewrite the text a string value holds, leaving anything else alone."""
    if isinstance(value, Scalar) and value.kind == "string":
        value.replace_text(rewrite(value.text))


def _text_of(value: Value) -> str | None:
    return value.text if isinstance(value, Scalar) and value.kind == "string" else None


# -- classifiers ---------------------------------------------------------------------------------


def _generate_classifiers(
    document: Document,
    *,
    max_supported_python: tuple[int, int],
    min_supported_python: tuple[int, int],
    wanted: bool,
) -> None:
    if not wanted or _names_dynamic(document):
        return
    requires_python, existing = _read_range_and_classifiers(document)
    held = classifier_rules.supported(requires_python, max_supported_python, min_supported_python)
    if held is None:
        return
    if existing is None:
        # written as something other than a list of classifiers; a second key would say it twice
        if not held.minors or _names_classifiers(document) or not _holds_a_project(document):
            return
        written = Array()
        _apply_classifiers(written, held, set())
        _write_classifiers(document, written)
        return

    def visit(key: str, value: Value) -> None:
        if key == "classifiers" and isinstance(value, Array):
            _apply_classifiers(value, held, existing)

    for_keys_under(document, PATH, visit)


def _apply_classifiers(array: Array, held: classifier_rules.Supported, existing: set[str]) -> None:
    """Ones outside the range go, ones inside that are missing arrive, the rest are left alone."""
    must_have = held.must_have()
    array.members = [
        member
        for member in array.members
        if (text := text_of(member)) is None or not text.startswith(classifier_rules.PREFIX) or text in must_have
    ]
    for add in sorted(held.worth_writing() - existing):
        array.members.append(Member(value=Scalar.of_string(add)))
    # a trailing comma holds the array open, which is where a generated list belongs
    array.trailing_comma = True


def _read_range_and_classifiers(document: Document) -> tuple[str | None, set[str] | None]:
    found: dict[str, object] = {}

    def visit(key: str, value: Value) -> None:
        if key == "requires-python":
            found["requires"] = _text_of(value)
        elif key == "classifiers" and isinstance(value, Array):
            found["classifiers"] = {text for member in value.members if (text := text_of(member)) is not None}

    for_keys_under(document, PATH, visit)
    requires = found.get("requires")
    classifiers = found.get("classifiers")
    return (requires if isinstance(requires, str) else None), (classifiers if isinstance(classifiers, set) else None)


def _names_dynamic(document: Document) -> bool:
    """Whether the project leaves the classifiers, or what they are read from, to its backend."""
    held = [False]

    def visit(key: str, value: Value) -> None:
        if key == "dynamic" and isinstance(value, Array):
            names = {text for member in value.members if (text := text_of(member)) is not None}
            held[0] = held[0] or bool(names & {"classifiers", "requires-python"})

    for_keys_under(document, PATH, visit)
    return held[0]


def _names_classifiers(document: Document) -> bool:
    held = [False]

    def visit(key: str, _value: Value) -> None:
        held[0] = held[0] or key == "classifiers"

    for_keys_under(document, PATH, visit)
    return held[0]


def _holds_a_project(document: Document) -> bool:
    """Whether the file says there is a project at all."""
    if any(section.name[: len(PATH)] == PATH for section in document.sections):
        return True
    held = [False]

    def visit(_key: str, _value: Value) -> None:
        held[0] = True

    for_keys_under(document, PATH, visit)
    return held[0] or _table_at(document) is not None


def _table_at(document: Document) -> InlineTable | None:
    """The project written as a value, where the file wrote it that way."""
    for under, entry in document.entries():
        if (*under, *entry.key) == PATH and isinstance(entry.value, InlineTable):
            return entry.value
    return None


def _write_classifiers(document: Document, value: Array) -> None:
    """Write the classifiers into the run of keys the project is already written in."""
    table = _table_at(document)
    if table is not None:
        table.entries.append(Entry(key=("classifiers",), value=value))
        return
    for section in document.sections:
        if section.name == PATH:
            section.entries.append(Entry(key=("classifiers",), value=value))
            return
    # only a run written at or above the project can hold a key of it
    for under, entries in _entry_runs(document):
        if len(under) > len(PATH) or PATH[: len(under)] != under:
            continue
        rest = PATH[len(under) :]
        holds = any(
            len((*under, *entry.key)) > len(PATH) and (*under, *entry.key)[: len(PATH)] == PATH for entry in entries
        )
        if holds:
            entries.append(Entry(key=(*rest, "classifiers"), value=value))
            return
    # no run of the file writes a key of the project, so the key that says it goes before the
    # first header, where it names the whole path it belongs to
    document.root.append(Entry(key=(*PATH, "classifiers"), value=value))


def _entry_runs(document: Document) -> list[tuple[KeyPath, list[Entry]]]:
    return [((), document.root), *((section.name, section.entries) for section in document.sections)]


# -- extras and people ---------------------------------------------------------------------------


def _normalize_extra_names(document: Document) -> None:
    """Write the normalized spelling of an extra, so two spellings do not look like two extras."""
    # a key the file wrote as a comment reserves no name: the comment comes back over it, and what
    # is left is the keys the file wrote
    held = active_entries(document)
    taken = {
        (*under, *entry.key)[len(PATH) :]
        for under, entry in held
        if len((*under, *entry.key)) > len(PATH) and (*under, *entry.key)[: len(PATH)] == PATH
    }
    for under, entry in held:
        named = (*under, *entry.key)
        if len(named) != len(PATH) + 2 or named[: len(PATH)] != PATH:
            continue
        field, extra = named[len(PATH) :]
        # an extra is a distribution name, and text that is not one is left for the backend to
        # report rather than rewritten into something else that is not one either
        if field != "optional-dependencies" or not names_a_distribution(extra):
            continue
        written = _SEPARATORS.sub("-", extra.lower())
        if written == extra or (field, written) in taken:
            continue
        entry.key = (*entry.key[:-1], written)
        taken.add((field, written))


def _order_array_elements(document: Document, name: KeyPath, key_order: tuple[str, ...]) -> None:
    """Put the keys of each element of an array of tables, or each inline table, in order."""
    for section in document.sections:
        if section.name == name and section.kind == "array":
            section.entries.sort(key=lambda entry: _person_rank(entry.key, key_order))
    for under, entry in active_entries(document):
        if (*under, *entry.key) != name or not isinstance(entry.value, Array):
            continue
        for member in entry.value.members:
            if isinstance(member.value, InlineTable):
                member.value.entries.sort(key=lambda held: _person_rank(held.key, key_order))


def _person_rank(key: KeyPath, key_order: tuple[str, ...]) -> tuple[int, str]:
    name = dotted_name(key)
    return (key_order.index(name) if name in key_order else len(key_order)), name


def _expand_array_of_tables(document: Document, name: KeyPath) -> None:
    """Write `authors = [{ name = "…" }]` out as `[[project.authors]]`."""
    if any(section.name == name for section in document.sections):
        return
    parent = next((section for section in document.sections if section.name == name[:-1]), None)
    if parent is None:
        return
    at = next((at for at, entry in enumerate(parent.entries) if entry.key == name[-1:]), None)
    if at is None:
        return
    array = parent.entries[at].value
    # every member has to have a written form, or the array stays as it is: writing out only the
    # ones that convert would drop the rest of what the file says
    if not isinstance(array, Array) or array.trailing or parent.entries[at].comment is not None:
        return
    written: list[Section] = []
    for member in array.members:
        if not isinstance(member.value, InlineTable) or member.comment is not None or any(member.lead):
            return
        fields = [Entry(key=held.key, value=held.value) for held in member.value.entries]
        fields.sort(key=lambda entry: _person_rank(entry.key, PEOPLE_KEY_ORDER))
        written.append(Section(name=name, kind="array", entries=fields))
    if not written:
        return
    # what led the entry leads the first header it becomes
    written[0].lead = parent.entries.pop(at).lead
    parent_at = document.sections.index(parent)
    for offset, section in enumerate(written):
        document.sections.insert(parent_at + 1 + offset, section)


# -- entry points --------------------------------------------------------------------------------


def _expand_entry_points(document: Document) -> None:
    """`entry-points.group = { name = "t" }` says what `entry-points.group.name = "t"` says.

    The dotted form is what the key order and the rest of the rules expect.
    """
    for under, entries in _entry_runs(document):
        entries[:] = _expanded_run(entries, under)


def _expanded_run(entries: list[Entry], under: KeyPath) -> list[Entry]:
    expanded: list[Entry] = []
    for entry in entries:
        named = (*under, *entry.key)
        key = dotted_name(named[len(PATH) :]) if named[: len(PATH)] == PATH else ""
        table = entry.value
        if (
            not key.startswith("entry-points.")
            or not isinstance(table, InlineTable)
            or not table.entries
            or table.trailing
            or is_enabled_here(entry)
        ):
            expanded.append(entry)
            continue
        last = len(table.entries) - 1
        for index, member in enumerate(table.entries):
            # a comment runs to the end of its line, so each one the member carried takes one
            around = [*member.lead, *([member.comment] if member.comment else [])]
            expanded.append(
                Entry(
                    key=(*entry.key, *member.key),
                    value=member.value,
                    # what led the table leads the first key it becomes
                    lead=[*(entry.lead if index == 0 else []), *around],
                    # the comment closing the table's line closes the last key it becomes
                    comment=entry.comment if index == last else None,
                )
            )
    return expanded
