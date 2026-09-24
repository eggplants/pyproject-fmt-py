"""The `[tool.poetry]` table.

Its sub-tables are written either as headers of their own or folded into the parent as dotted keys,
and the same rules read both. The dependency groups a file happens to define each get their own
slot in the key order, so a group's keys land where that group does.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..arrays import dedupe_strings_in, sort_names_in
from ..keys import render_segment
from ..ordering import reorder_keys
from ..sections import (
    InlineSchema,
    first_section,
    for_entries,
    for_keys_under,
    for_names_under,
    for_value_at,
    headers_below,
    reorder_array_tables_at,
    reorder_inline_tables,
    reorder_under,
    sort_names_under,
)
from . import _data as d

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..document import Document, Entry, Value
    from ..keys import KeyPath

PATH: KeyPath = ("tool", "poetry")

#: Deprecated source keys sort last, so reordering never promotes them above the current ones.
SOURCE_KEY_ORDER = d.POETRY_SOURCE_KEY_ORDER
BUILD_KEY_ORDER = d.POETRY_BUILD_KEY_ORDER
GROUP_KEY_ORDER = d.POETRY_GROUP_KEY_ORDER

#: Inside the dependency tables, `python` is the interpreter constraint and leads; the rest sort.
DEPENDENCIES_KEY_ORDER = d.POETRY_DEPENDENCIES_KEY_ORDER

#: A discriminator is poetry-specific, so an inline table in another tool's section that shares a
#: generic key such as `name` or `url` is not mistaken for one of these.
INLINE_SCHEMAS: tuple[InlineSchema, ...] = (
    *(InlineSchema(name, d.POETRY_SOURCE_INLINE_KEYS) for name in ("priority", "links", "indexed", "secondary")),
    InlineSchema("git", d.POETRY_GIT_DEP_INLINE_KEYS),
    InlineSchema("path", d.POETRY_PATH_DEP_INLINE_KEYS),
    InlineSchema("file", d.POETRY_FILE_DEP_INLINE_KEYS),
)

#: The tables whose entries are a package name paired with what it asks for.
_DEPENDENCY_TABLES = ("dependencies", "dev-dependencies", "requires-plugins", "build-constraints")


def fix(document: Document) -> None:
    """Sort what the table holds and put its keys, and those of its sub-tables, in order."""
    _fix_root(document)
    _fix_expanded_sub_tables(document)
    _fix_source(document)


def reorder_inline_tables_of(document: Document) -> None:
    """Order the inline tables the schemas recognize."""
    reorder_inline_tables(document, PATH, INLINE_SCHEMAS)


def _fix_root(document: Document) -> None:
    for_keys_under(document, PATH, _sort_root_value)
    tails: list[KeyPath] = []

    def gather(tail: KeyPath, _entry: Entry) -> None:
        tails.append(tail)

    for_names_under(document, PATH, gather)
    for tail in tails:
        if _is_a_name_set(tail):
            for_value_at(document, (*PATH, *tail), sort_names_in)
    reorder_under(document, PATH, root_key_order(_group_names(document)))


def _sort_root_value(key: str, value: Value) -> None:
    # a keyword is free text, while a classifier is one of a fixed set of strings: two that differ
    # in case are an invalid spelling beside a valid one rather than one claim twice
    if key == "keywords":
        dedupe_strings_in(value, str.lower)
        sort_names_in(value)
    elif key == "classifiers":
        dedupe_strings_in(value)
        sort_names_in(value)
    elif key == "exclude":
        sort_names_in(value)


def _is_a_name_set(tail: KeyPath) -> bool:
    """Extras lists, include-groups and per-dependency extras are name sets, so they sort."""
    if len(tail) == 2 and tail[0] == "extras":  # noqa: PLR2004 - the field then the extra
        return True
    # the group's name is the one segment after `group`, whatever it holds
    if tail[:1] == ("group",) and len(tail) > 2:  # noqa: PLR2004 - `group`, its name, then a key
        rest = tail[2:]
        if rest == ("include-groups",):
            return True
        return rest[0] == "dependencies" and _is_dependency_extras(rest[1:])
    if tail[:1] and tail[0] in _DEPENDENCY_TABLES:
        return _is_dependency_extras(tail[1:])
    return False


def _is_dependency_extras(tail: KeyPath) -> bool:
    """`<package>.extras`, whatever the package is called."""
    return len(tail) == 2 and tail[1] == "extras"  # noqa: PLR2004 - the package then the field


def _group_names(document: Document) -> list[str]:
    groups: list[str] = []

    def gather(tail: KeyPath, _entry: Entry) -> None:
        if len(tail) >= 2 and tail[0] == "group" and tail[1] not in groups:  # noqa: PLR2004 - `group` then its name
            groups.append(tail[1])

    for_names_under(document, PATH, gather)
    return groups


def root_key_order_of(entries: Sequence[Entry]) -> tuple[str, ...]:
    """The key order read from the names one table holds, however the file split their paths."""
    groups: list[str] = []
    for entry in entries:
        if len(entry.key) >= 2 and entry.key[0] == "group" and entry.key[1] not in groups:  # noqa: PLR2004
            groups.append(entry.key[1])
    return root_key_order(groups)


def root_key_order(group_names: Sequence[str]) -> tuple[str, ...]:
    """The key order, with a slot of its own for each dependency group the file defines."""
    order = list(d.POETRY_TOP_LEVEL_ORDER)
    # `build` may be a scalar, an inline table, or dotted sub-keys, and the bare prefix catches
    # whichever form the file wrote
    order += ["build.script", "build.generate-setup-file", "build"]
    order += ["dependencies.python", "dependencies", "dev-dependencies"]
    for group in group_names:
        # the name is spelled the way a rule spells one, so both sides match
        held = render_segment(group)
        order += [
            f"group.{held}.optional",
            f"group.{held}.include-groups",
            f"group.{held}.dependencies.python",
            f"group.{held}.dependencies",
        ]
    order += ["group", "extras", "scripts", "plugins", "urls", "source"]
    order += ["requires-poetry", "requires-plugins", "build-constraints"]
    return tuple(order)


def _fix_expanded_sub_tables(document: Document) -> None:
    """In the long format the sub-tables stay as headers of their own, so each is ordered here."""
    for table in _DEPENDENCY_TABLES:
        _order_dependencies(document, (*PATH, table))
    sort_names_under(document, (*PATH, "extras"))
    for table in ("scripts", "urls"):
        _order_alphabetically(document, (*PATH, table))
    _fix_expanded_plugins(document)
    _fix_expanded_groups(document)
    section = first_section(document, (*PATH, "build"))
    if section is not None:
        reorder_keys(section.entries, BUILD_KEY_ORDER)


def _order_dependencies(document: Document, name: KeyPath) -> None:
    section = first_section(document, name)
    if section is not None:
        reorder_keys(section.entries, DEPENDENCIES_KEY_ORDER)


def _order_alphabetically(document: Document, name: KeyPath) -> None:
    section = first_section(document, name)
    if section is not None:
        reorder_keys(section.entries, ())


def _fix_expanded_plugins(document: Document) -> None:
    plugins = (*PATH, "plugins")
    for section in document.sections:
        if section.name == plugins or (len(section.name) > len(plugins) and section.name[: len(plugins)] == plugins):
            reorder_keys(section.entries, ())


def _fix_expanded_groups(document: Document) -> None:
    for group in headers_below(document, (*PATH, "group")):
        name = (*PATH, "group", group)
        section = first_section(document, name)
        if section is not None:
            for_entries(section, _sort_include_groups)
            reorder_keys(section.entries, GROUP_KEY_ORDER)
        _order_dependencies(document, (*name, "dependencies"))


def _sort_include_groups(key: str, value: Value) -> None:
    if key == "include-groups":
        sort_names_in(value)


def _fix_source(document: Document) -> None:
    source = (*PATH, "source")
    for section in document.sections_named(source):
        reorder_keys(section.entries, SOURCE_KEY_ORDER)
    # a source folded into its parent is a table inside an array, and it is one source either way
    reorder_array_tables_at(document, source, SOURCE_KEY_ORDER)
