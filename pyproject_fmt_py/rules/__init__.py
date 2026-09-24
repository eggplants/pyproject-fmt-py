"""Which tables the formatter recognizes, and what each of them asks for.

Most of a tool table's formatting is its key order and which of its arrays hold a set of names;
those tables are written out here as data. The ones with rules of their own live in modules beside
this one and register the order their sub-tables are written in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import ordering
from ..arrays import dedupe_strings_in, sort_names_in
from ..keys import dotted_name, parse_key_path
from ..sections import for_keys_under, reorder_under
from ..spacing import NESTED_PREFIXES
from . import _data as d
from ._spec import TableRule, among, either, leaf_among, nothing, under

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from ..document import Document, Entry, Value
    from ..keys import KeyPath

__all__ = ["TableRule", "every_order", "fix", "order_of", "reorder_tables", "rule_for"]

_BANDIT_INNER = leaf_among("skips", "tmp_dirs", "no_shell", "shell", "subprocess", "tests")


def _bandit_sorts(key: str) -> bool:
    return key in d.BANDIT_SORT_ARRAYS_EXACT or ("." in key and _BANDIT_INNER(key))


_PYLINT_SORTS = leaf_among(
    "enable",
    "disable",
    "extension-pkg-allow-list",
    "extension-pkg-whitelist",
    "ignore",
    "ignore-patterns",
    "ignore-paths",
    "ignored-modules",
    "ignored-classes",
    "ignored-argument-names",
    "good-names",
    "bad-names",
    "init-import",
    "logging-modules",
    "valid-classmethod-first-arg",
    "valid-metaclass-classmethod-first-arg",
    "callbacks",
    "additional-builtins",
    "allowed-redefined-builtins",
    "dummy-variables-rgx",
    "exclude-too-few-public-methods",
    "deprecated-modules",
    "known-third-party",
    "known-standard-library",
    "allowed-modules",
    "expected-line-ending-format",
    "overgeneral-exceptions",
    "defining-attr-methods",
    "exclude-protected",
    "valid-class-attribute-rgx",
)

_COVERAGE_SORTS = among(
    "run.source",
    "run.source_pkgs",
    "run.source_dirs",
    "run.include",
    "run.omit",
    "run.concurrency",
    "run.debug",
    "run.disable_warnings",
    "report.include",
    "report.omit",
    "report.exclude_lines",
    "report.exclude_also",
    "report.partial_branches",
    "report.partial_also",
)

_RUFF_SORTS = either(
    among(*d.RUFF_SORTS),
    under("lint.extend-per-file-ignores.", "lint.per-file-ignores."),
)

_UV_PIP_SORTS = among(
    "allow-insecure-host",
    "extra",
    "no-binary-package",
    "no-build-isolation-package",
    "no-build-package",
    "no-emit-package",
    "only-binary-package",
    "reinstall-package",
    "upgrade-package",
)

#: The tables whose formatting is their key order and which of their arrays name a set.
PLAIN: tuple[TableRule, ...] = (
    TableRule("tool.autopep8", d.AUTOPEP8_KEY_ORDER, among(*d.AUTOPEP8_SORT_ARRAYS)),
    TableRule("tool.bandit", d.BANDIT_KEY_ORDER, _bandit_sorts),
    TableRule("tool.black", d.BLACK_KEY_ORDER, among("target-version", "enable-unstable-feature")),
    TableRule("tool.bumpversion", d.BUMPVERSION_KEY_ORDER, nothing),
    TableRule("tool.check-manifest", d.CHECK_MANIFEST_KEY_ORDER, among(*d.CHECK_MANIFEST_SORT_ARRAYS)),
    # coverage maps a file with the first `[paths]` group that matches
    TableRule("tool.coverage", d.COVERAGE_KEY_ORDER, _COVERAGE_SORTS, keeps_order=("paths",)),
    TableRule("tool.codespell", d.CODESPELL_KEY_ORDER, among(*d.CODESPELL_SORT_ARRAYS)),
    TableRule("tool.commitizen", d.COMMITIZEN_KEY_ORDER, among(*d.COMMITIZEN_SORT_ARRAYS)),
    TableRule("tool.deptry", d.DEPTRY_KEY_ORDER, among(*d.DEPTRY_SORT_ARRAYS)),
    TableRule("tool.djlint", d.DJLINT_KEY_ORDER, among(*d.DJLINT_SORT_ARRAYS)),
    TableRule("tool.docformatter", d.DOCFORMATTER_KEY_ORDER, nothing),
    TableRule("tool.interrogate", d.INTERROGATE_KEY_ORDER, among(*d.INTERROGATE_SORT_ARRAYS)),
    TableRule("tool.isort", d.ISORT_KEY_ORDER, among(*d.ISORT_SORT_ARRAYS)),
    TableRule("tool.maturin", d.MATURIN_KEY_ORDER, among(*d.MATURIN_SORT_ARRAYS)),
    TableRule("tool.pylint", d.PYLINT_KEY_ORDER, _PYLINT_SORTS),
    # every one of them is read as a set, so a name written twice says no more than once
    TableRule(
        "tool.pyproject-fmt",
        d.PYPROJECT_FMT_KEY_ORDER,
        among(*d.PYPROJECT_FMT_SORT_ARRAYS),
        dedupes=among(*d.PYPROJECT_FMT_SORT_ARRAYS),
    ),
    TableRule("tool.pyrefly", d.PYREFLY_KEY_ORDER, among(*d.PYREFLY_SORT_ARRAYS)),
    TableRule("tool.pixi", d.PIXI_KEY_ORDER, among("workspace.platforms", "workspace.preview")),
    TableRule("tool.pixi.workspace", d.PIXI_WORKSPACE_KEY_ORDER, among("platforms", "preview")),
    TableRule("tool.pytest", d.PYTEST_KEY_ORDER, among(*d.PYTEST_SORT_ARRAYS)),
    TableRule("tool.ruff", d.RUFF_KEY_ORDER, _RUFF_SORTS),
    TableRule("tool.scikit-build", d.SCIKIT_BUILD_KEY_ORDER, leaf_among("files", "exclude-fields")),
    # the branch rules are read in order and the first match decides the release policy
    TableRule(
        "tool.semantic_release",
        d.SEMANTIC_RELEASE_KEY_ORDER,
        among(*d.SEMANTIC_RELEASE_SORT_ARRAYS),
        keeps_order=("branches",),
    ),
    TableRule("tool.ty", d.TY_KEY_ORDER, among(*d.TY_SORT_ARRAYS)),
    TableRule("tool.ty.src", d.TY_SRC_KEY_ORDER, among("include")),
    TableRule("tool.mypy", d.MYPY_KEY_ORDER, among(*d.MYPY_TOP_LEVEL_SORT_ARRAYS)),
    TableRule("tool.pdm", d.PDM_KEY_ORDER, either(among(*d.PDM_SORT_ARRAYS_EXACT), under("dev-dependencies."))),
    TableRule(
        "tool.setuptools",
        d.SETUPTOOLS_KEY_ORDER,
        either(among(*d.SETUPTOOLS_TOP_LEVEL_SORT_ARRAYS), under("package-data.", "exclude-package-data.")),
    ),
    TableRule("tool.towncrier", d.TOWNCRIER_KEY_ORDER, among("ignore")),
    TableRule("tool.uv", d.UV_KEY_ORDER, among(*d.UV_SORTS)),
    TableRule("tool.uv.pip", d.UV_PIP_KEY_ORDER, _UV_PIP_SORTS),
    # a source names one dependency, and nothing ranks one above another
    TableRule("tool.uv.sources", (), nothing),
    TableRule("tool.vulture", d.VULTURE_KEY_ORDER, among(*d.VULTURE_SORT_ARRAYS)),
    TableRule("tool.yapf", d.YAPF_KEY_ORDER, nothing),
)

#: The key order of the tables their own module formats, so a sub-table written out lines up with
#: the dotted-key form.
ORDERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("project", d.PROJECT_KEY_ORDER),
    ("tool.cibuildwheel", d.CIBUILDWHEEL_KEY_ORDER),
    ("tool.hatch", d.HATCH_KEY_ORDER),
    ("tool.pyright", d.PYRIGHT_KEY_ORDER_PRE_REPORTS),
    ("tool.basedpyright", d.PYRIGHT_KEY_ORDER_PRE_REPORTS),
    ("tool.setuptools_scm", d.SETUPTOOLS_SCM_KEY_ORDER),
)

#: Where each table sits in a formatted file.
TABLE_ORDER: tuple[str, ...] = d.GLOBAL_TABLE_ORDER

_BY_TABLE = {rule.table: rule for rule in PLAIN}
_ORDER_BY_TABLE = dict(ORDERS) | {rule.table: rule.order for rule in PLAIN if rule.order}

#: The tables whose children hold the place the file gave them, since a tool runs its hooks and
#: applies its overrides in the order they are written.
KEEP_WITHIN: dict[str, tuple[str, ...]] = {
    "tool.hatch": ("hooks", "overrides", "matrix"),
    "tool.coverage": ("paths",),
    "tool.semantic_release": ("branches",),
}


def rule_for(table: str) -> TableRule | None:
    """The rules for the table spelled `table`, or None where the formatter has no policy."""
    return _BY_TABLE.get(table)


def order_of(table: str) -> tuple[str, ...] | None:
    """Where the keys of the table sit, whichever module formats them."""
    return _ORDER_BY_TABLE.get(table)


def every_order() -> Iterator[tuple[str, tuple[str, ...]]]:
    """Every table the formatter ranks the keys of, with that ranking."""
    for rule in PLAIN:
        if rule.order:
            yield rule.table, rule.order
    yield from ORDERS


def fix(document: Document) -> None:
    """Format every table these rules speak for: its arrays, then its key order."""
    for rule in PLAIN:
        path = parse_key_path(rule.table)

        def visit(name: str, value: Value, rule: TableRule = rule) -> None:
            if rule.dedupes(name):
                dedupe_strings_in(value)
            if rule.sorts(name):
                sort_names_in(value)

        for_keys_under(document, path, visit)
        reorder_under(document, path, rule.order, rule.keeps_order)


def reorder_tables(document: Document) -> None:
    """Put every table where a formatted file writes it, and its keys in the order it writes them."""
    ordering.reorder_tables(document, TABLE_ORDER, NESTED_PREFIXES, _key_order, _keep_within)
    for section in document.sections:
        name = dotted_name(section.name)
        # a tool that builds its order from the file gets that order here too, or this pass would
        # rank the keys it discovered as though the file had never named them
        order = built_order(name, section.entries) or order_of(name)
        if order is None:
            continue
        ordering.reorder_keys(section.entries, order, built_keep_order(name, section.entries))


def built_order(table: str, entries: Sequence[Entry]) -> tuple[str, ...] | None:
    """The order a tool builds from the file itself, since the keys it ranks are the ones it holds.

    Ordering a table twice with a different order would undo the first, so the pass that ranks a
    table's keys and the one that places its sub-tables read the same answer.
    """
    from . import hatch, poetry, tools  # noqa: PLC0415 - the rules read the registry they are in

    if table == "tool.poetry":
        return poetry.root_key_order_of(entries)
    if table == "tool.hatch":
        return hatch.key_order_of(entries)
    if table in {"tool.pyright", "tool.basedpyright"}:
        return tools.pyright_key_order_of(entries)
    return None


def built_keep_order(table: str, entries: Sequence[Entry]) -> tuple[str, ...]:
    """The names whose keys hold the order the file gave them."""
    from . import hatch  # noqa: PLC0415 - the rules read the registry they are in

    if table == "tool.hatch":
        return hatch.keep_order_of(entries)
    return KEEP_WITHIN.get(table, ())


def _key_order(table: KeyPath) -> tuple[str, ...] | None:
    """Where a sub-table sits among its parent's keys.

    Ranking needs no file context, so the order a tool builds from the file is taken with none.
    """
    name = dotted_name(table)
    return built_order(name, ()) or order_of(name)


def _keep_within(table: KeyPath) -> tuple[str, ...]:
    return KEEP_WITHIN.get(dotted_name(table), ())
