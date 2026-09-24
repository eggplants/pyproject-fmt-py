"""The `[tool.hatch]` table.

The environments a file happens to define each get their own run of slots in the key order, so an
environment's keys land where that environment does.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..arrays import sort_names_in
from ..keys import render_segment
from ..ordering import reorder_keys
from ..sections import (
    first_section,
    for_names_under,
    for_value_at,
    headers_below,
    reorder_under,
)
from ..sections import for_entries as for_entries_of
from . import _data as d

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..document import Document, Entry, Value
    from ..keys import KeyPath

PATH: KeyPath = ("tool", "hatch")

#: hatch reads `include`, `exclude` and `artifacts` the way a gitignore is read, where a `!pattern`
#: after a broader one takes back what it matched, so each of those keeps the order it was written
#: in. What is left here selects files by name alone.
SORT_ARRAYS_EXACT = frozenset(d.HATCH_SORT_ARRAYS_EXACT)

#: Where each key of one environment sits.
ENV_KEY_ORDER: tuple[str, ...] = (
    "type",
    "template",
    "detached",
    "description",
    "platforms",
    "python",
    "path",
    "installer",
    "skip-install",
    "system-packages",
    "dev-mode",
    "features",
    "dependencies",
    "extra-dependencies",
    "extra-args",
    "pre-install-commands",
    "post-install-commands",
    "env-include",
    "env-exclude",
    "env-vars",
    "scripts",
    "matrix",
    "matrix-name-format",
    "overrides",
)

#: The per-environment arrays that name a set, so they sort.
ENV_SORT_ARRAYS = frozenset(
    {"dependencies", "extra-dependencies", "features", "platforms", "env-include", "env-exclude"}
)


def fix(document: Document) -> None:
    """Sort what the table holds and put its keys, and each environment's, in order."""
    _fix_root(document)
    _fix_env_tables(document)


def _fix_root(document: Document) -> None:
    names: list[KeyPath] = []

    def gather(tail: KeyPath, _entry: Entry) -> None:
        names.append(tail)

    for_names_under(document, PATH, gather)
    # the name a rule reads here is the key's own segments, so an environment the file quoted
    # because it holds a dot is the one name it wrote
    for tail in names:
        if ".".join(tail) in SORT_ARRAYS_EXACT or _is_env_name_set(tail):
            for_value_at(document, (*PATH, *tail), sort_names_in)
    reorder_under(document, PATH, key_order(names), keep_order(names))


def _is_env_name_set(tail: KeyPath) -> bool:
    return len(tail) == 3 and tail[0] == "envs" and tail[2] in ENV_SORT_ARRAYS  # noqa: PLR2004 - envs, name, key


def key_order_of(entries: Sequence[Entry]) -> tuple[str, ...]:
    """The key order read from the names one table holds, however the file split their paths."""
    return key_order([entry.key for entry in entries])


def keep_order_of(entries: Sequence[Entry]) -> tuple[str, ...]:
    """The names that keep the file's order, read from what one table holds."""
    return keep_order([entry.key for entry in entries])


def key_order(names: Sequence[KeyPath]) -> tuple[str, ...]:
    """The key order, with a run of slots for each environment the file defines.

    `envs` is not in the written-down order: the per-environment entries go in first, and a bare
    `envs` closes the block so anything outside the canonical inner keys still lands in it.
    """
    order = list(d.HATCH_KEY_ORDER)
    for env in _below(names, ("envs",)):
        prefix = f"envs.{render_segment(env)}"
        order += [f"{prefix}.{name}" for name in ENV_KEY_ORDER]
        order.append(prefix)
    order.append("envs")
    return tuple(order)


def keep_order(names: Sequence[KeyPath]) -> tuple[str, ...]:
    """The names whose keys hold the order the file gave them.

    hatch runs its hooks and applies its overrides in the order they are written, and reads a
    matrix element in that order to build the names it generates.
    """
    held = ["build.hooks", "metadata.hooks"]
    held += [f"build.targets.{render_segment(target)}.hooks" for target in _below(names, ("build", "targets"))]
    for env in _below(names, ("envs",)):
        name = render_segment(env)
        held += [f"envs.{name}.overrides", f"envs.{name}.matrix"]
    return tuple(held)


def _below(names: Sequence[KeyPath], prefix: KeyPath) -> list[str]:
    """The one segment each name writes below `prefix`, in the order they read."""
    held = {name[len(prefix)] for name in names if len(name) > len(prefix) and name[: len(prefix)] == prefix}
    return sorted(held)


def _fix_env_tables(document: Document) -> None:
    for env in headers_below(document, (*PATH, "envs")):
        name = (*PATH, "envs", env)
        section = first_section(document, name)
        if section is not None:
            for_entries_of(section, _sort_env_value)
            reorder_keys(section.entries, ENV_KEY_ORDER)
        for sub in ("scripts", "env-vars"):
            held = first_section(document, (*name, sub))
            if held is not None:
                reorder_keys(held.entries, ())


def _sort_env_value(key: str, value: Value) -> None:
    if key in ENV_SORT_ARRAYS:
        sort_names_in(value)
