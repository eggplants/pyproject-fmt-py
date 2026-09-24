"""The `[tool.setuptools]` and `[tool.setuptools_scm]` tables."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..arrays import sort_names_in
from ..keys import render_segment
from ..ordering import reorder_keys
from ..sections import InlineSchema, first_section, for_entries, reorder_inline_tables
from . import _data as d

if TYPE_CHECKING:
    from ..document import Document, Value
    from ..keys import KeyPath

PATH: KeyPath = ("tool", "setuptools")

PACKAGES_FIND_KEY_ORDER = ("where", "include", "exclude", "namespaces")

#: `attr` and `content-type` are unique to a dynamic directive; `file` is too generic to name one.
INLINE_SCHEMAS: tuple[InlineSchema, ...] = (
    InlineSchema("attr", d.SETUPTOOLS_DYNAMIC_DIRECTIVE_ORDER),
    InlineSchema("content-type", d.SETUPTOOLS_DYNAMIC_DIRECTIVE_ORDER),
)

#: `*` is not a name TOML reads bare, so the file writes it in quotes and a rule spells it the same.
_CATCH_ALL = render_segment("*")


def fix(document: Document) -> None:
    """Order what each of the sub-tables holds, whichever way the file wrote it."""
    _order_section(document, ("tool", "setuptools_scm"), d.SETUPTOOLS_SCM_KEY_ORDER)
    for name in ("find", "find-namespace"):
        _fix_packages_find(document, (*PATH, "packages", name))
    _order_section(document, (*PATH, "dynamic"), ())
    for name in ("package-data", "exclude-package-data"):
        _fix_data_table(document, (*PATH, name), patterns_are_a_set=True)
    _fix_data_table(document, (*PATH, "data-files"), patterns_are_a_set=False)
    _order_section(document, (*PATH, "cmdclass"), ())


def reorder_inline_tables_of(document: Document) -> None:
    """Order the dynamic directives the schemas recognize."""
    reorder_inline_tables(document, PATH, INLINE_SCHEMAS)


def _order_section(document: Document, name: KeyPath, order: tuple[str, ...]) -> None:
    section = first_section(document, name)
    if section is not None:
        reorder_keys(section.entries, order)


def _fix_packages_find(document: Document, name: KeyPath) -> None:
    section = first_section(document, name)
    if section is None:
        return
    for_entries(section, _sort_selections)
    reorder_keys(section.entries, PACKAGES_FIND_KEY_ORDER)


def _sort_selections(key: str, value: Value) -> None:
    if key in {"include", "exclude"}:
        sort_names_in(value)


def _fix_data_table(document: Document, name: KeyPath, *, patterns_are_a_set: bool) -> None:
    """The `*` catch-all leads, then the destinations alphabetically."""
    section = first_section(document, name)
    if section is None:
        return
    others: list[str] = []

    def visit(key: str, value: Value) -> None:
        if patterns_are_a_set:
            sort_names_in(value)
        # a table names each of its keys once, so the catch-all is the only one that does not sort
        if key != _CATCH_ALL:
            others.append(key)

    for_entries(section, visit)
    reorder_keys(section.entries, ("", _CATCH_ALL, *sorted(others)))
