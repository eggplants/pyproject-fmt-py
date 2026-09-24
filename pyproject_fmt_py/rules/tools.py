"""The tool tables whose rules go past a key order and a list of sortable arrays.

Each of them is read the same way: what the file wrote as headers and what the short format folded
into inline tables say the same thing, so both forms get the same treatment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..arrays import sort_names_in
from ..keys import dotted_name, parse_key_path
from ..ordering import rank, reorder_keys
from ..sections import (
    InlineSchema,
    first_section,
    for_array_elements,
    for_entries,
    for_keys_under,
    for_value_at,
    reorder_array_tables_at,
    reorder_inline_tables,
    reorder_under,
    sort_names_under,
)
from ..sorting import natural_lexical_key
from . import _data as d

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..document import Document, Entry, Value
    from ..keys import KeyPath

# -- towncrier -----------------------------------------------------------------------------------

TOWNCRIER_TYPE_KEY_ORDER = ("directory", "name", "showcontent")
TOWNCRIER_SECTION_KEY_ORDER = ("path", "name", "showcontent")


def towncrier_fix(document: Document) -> None:
    """Order the keys of each `[[tool.towncrier.type]]` and `[[tool.towncrier.section]]`."""
    for_array_elements(document, ("tool", "towncrier", "type"), TOWNCRIER_TYPE_KEY_ORDER)
    for_array_elements(document, ("tool", "towncrier", "section"), TOWNCRIER_SECTION_KEY_ORDER)


# -- pyright -------------------------------------------------------------------------------------

#: `extraPaths` is the order the roots are searched in, so what it says depends on where each one
#: sits; the rest only select files.
PYRIGHT_SORT_ARRAYS = frozenset({"include", "exclude", "ignore", "strict"})


def pyright_fix(document: Document) -> None:
    """Order both pyright tables, with their `report*` rules alphabetized between the fixed blocks."""
    for table in ("tool.pyright", "tool.basedpyright"):
        path = parse_key_path(table)
        names: list[str] = []

        def gather(key: str, value: Value, names: list[str] = names) -> None:  # noqa: ARG001
            names.append(key)

        for_keys_under(document, path, gather)
        for_keys_under(document, path, _pyright_sort)
        reorder_under(document, path, pyright_key_order(names))


def _pyright_sort(key: str, value: Value) -> None:
    if key in PYRIGHT_SORT_ARRAYS:
        sort_names_in(value)


def pyright_key_order_of(entries: Sequence[Entry]) -> tuple[str, ...]:
    """The key order read from the names one table holds, however the file split their paths."""
    return pyright_key_order([dotted_name(entry.key) for entry in entries])


def pyright_key_order(names: Sequence[str]) -> tuple[str, ...]:
    """The order the table's keys read in, with the `report*` rules the file names in the middle.

    pyright has 70-odd diagnostic rules and basedpyright adds its own, so they are collected from
    the file rather than written down here: the list evolves between releases.
    """
    reports: list[str] = []
    for path in names:
        name = path.split(".", 1)[0]
        if name.startswith("report") and name not in reports:
            reports.append(name)
    reports.sort(key=lambda name: natural_lexical_key(name.lower()))
    return (*d.PYRIGHT_KEY_ORDER_PRE_REPORTS, *reports, *d.PYRIGHT_KEY_ORDER_POST_REPORTS)


# -- pdm -----------------------------------------------------------------------------------------

PDM_SOURCE_KEY_ORDER = d.PDM_SOURCE_KEY_ORDER


def pdm_fix(document: Document) -> None:
    """Order the scripts, the development dependencies and each `[[tool.pdm.source]]`."""
    section = first_section(document, ("tool", "pdm", "scripts"))
    if section is not None:
        reorder_keys(section.entries, ())
    sort_names_under(document, ("tool", "pdm", "dev-dependencies"))
    for_array_elements(document, ("tool", "pdm", "source"), PDM_SOURCE_KEY_ORDER, _pdm_source_sort)


def _pdm_source_sort(key: str, value: Value) -> None:
    if key in {"include_packages", "exclude_packages"}:
        sort_names_in(value)


# -- cibuildwheel --------------------------------------------------------------------------------

#: Most arrays are the argv of a command, whose order says something; only these name a set.
CIBUILDWHEEL_SORT_ARRAYS = frozenset(d.CIBUILDWHEEL_SORT_ARRAYS)

#: `select` leads because cibuildwheel asks for it on every override entry.
CIBUILDWHEEL_OVERRIDES_KEY_ORDER: tuple[str, ...] = (
    "",
    "select",
    *(name for name in d.CIBUILDWHEEL_KEY_ORDER if name and name != "overrides"),
)

_PLATFORMS = ("linux", "macos", "windows", "android", "ios", "pyodide")


def cibuildwheel_fix(document: Document) -> None:
    """Order the table, each per-platform table, and every override however the file wrote it."""
    _cibuildwheel_one(document, ("tool", "cibuildwheel"))
    # a per-platform table reuses the parent's order for when it stays written out
    for platform in _PLATFORMS:
        _cibuildwheel_one(document, ("tool", "cibuildwheel", platform))
    for section in document.sections_named(("tool", "cibuildwheel", "overrides")):
        for_entries(section, _cibuildwheel_sort)
        reorder_keys(section.entries, CIBUILDWHEEL_OVERRIDES_KEY_ORDER)


def _cibuildwheel_one(document: Document, path: KeyPath) -> None:
    def visit(key: str, value: Value) -> None:
        if key in CIBUILDWHEEL_SORT_ARRAYS:
            sort_names_in(value)
        elif key == "overrides":
            _cibuildwheel_overrides_inline(value)

    for_keys_under(document, path, visit)
    reorder_under(document, path, d.CIBUILDWHEEL_KEY_ORDER)


def _cibuildwheel_sort(key: str, value: Value) -> None:
    if key in CIBUILDWHEEL_SORT_ARRAYS:
        sort_names_in(value)


def _cibuildwheel_overrides_inline(value: Value) -> None:
    """An override folded into its parent gets what the written-out form gets."""
    from ..document import Array, InlineTable  # noqa: PLC0415 - read where the shape is

    if not isinstance(value, Array):
        return
    for member in value.members:
        table = member.value
        if not isinstance(table, InlineTable):
            continue
        # the discriminator is what says this inline table is an override rather than something else
        if not any(dotted_name(entry.key) == "select" for entry in table.entries):
            continue
        for entry in table.entries:
            _cibuildwheel_sort(dotted_name(entry.key), entry.value)
        table.entries.sort(key=lambda entry: _ranked(entry.key, CIBUILDWHEEL_OVERRIDES_KEY_ORDER))


# -- mypy ----------------------------------------------------------------------------------------

MYPY_OVERRIDES_KEY_ORDER = d.MYPY_OVERRIDES_KEY_ORDER

#: A module glob sorts too, which is what the rest of a formatted file does with a list of names.
MYPY_OVERRIDES_SORT_ARRAYS = frozenset(d.MYPY_OVERRIDES_SORT_ARRAYS)

#: A discriminator names a key mypy writes, not one no other tool may. Several of them map to the
#: same order, so an override writing only `module` and `ignore_missing_imports` is still one.
MYPY_INLINE_SCHEMAS: tuple[InlineSchema, ...] = tuple(
    InlineSchema(discriminator=name, key_order=MYPY_OVERRIDES_KEY_ORDER)
    for name in (
        "disable_error_code",
        "enable_error_code",
        "ignore_missing_imports",
        "follow_untyped_imports",
        "ignore_errors",
        "warn_unused_ignores",
        "disallow_untyped_defs",
        "check_untyped_defs",
    )
)

_MYPY_OVERRIDES = ("tool", "mypy", "overrides")


def mypy_fix(document: Document) -> None:
    """Order every override, whether the file wrote it out or folded it into its parent."""
    for section in document.sections_named(_MYPY_OVERRIDES):
        for_entries(section, _mypy_sort)
        reorder_keys(section.entries, MYPY_OVERRIDES_KEY_ORDER)
    reorder_array_tables_at(document, _MYPY_OVERRIDES, MYPY_OVERRIDES_KEY_ORDER)


def mypy_reorder_inline_tables(document: Document) -> None:
    """Order the inline tables the schemas recognize, and the arrays a folded override holds."""
    reorder_inline_tables(document, ("tool", "mypy"), MYPY_INLINE_SCHEMAS)
    for_value_at(document, _MYPY_OVERRIDES, _mypy_sort_inside)


def _mypy_sort(key: str, value: Value) -> None:
    if key in MYPY_OVERRIDES_SORT_ARRAYS:
        sort_names_in(value)


def _mypy_sort_inside(value: Value) -> None:
    """A folded `[[tool.mypy.overrides]]` puts its arrays inside a value, out of the entry walk."""
    from ..document import Array, InlineTable  # noqa: PLC0415 - read where the shape is

    if not isinstance(value, Array):
        return
    for member in value.members:
        if isinstance(member.value, InlineTable):
            for entry in member.value.entries:
                _mypy_sort(dotted_name(entry.key), entry.value)


def _ranked(key: KeyPath, order: Sequence[str]) -> tuple[int, str]:
    name = dotted_name(key)
    return rank(name, order), name.lower()
