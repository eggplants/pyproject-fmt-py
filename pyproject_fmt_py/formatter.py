"""The whole of what formatting a document does, either side of the rules themselves."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import disabled, document, nesting, render, rules, spacing, wrapping
from .errors import FormatError
from .rules import build_system, dependency_groups, hatch, poetry, project, setuptools, tools, tox

if TYPE_CHECKING:
    from .config import Settings
    from .keys import KeyPath

__all__ = ["FormatError", "format_toml"]


def format_toml(content: str, settings: Settings) -> str:
    """Format a `pyproject.toml` source.

    Args:
        content: The text of the file.
        settings: What the run was asked for.

    Returns:
        What the formatter writes for it.

    Raises:
        FormatError: If the source is not a document, or says something the rules reject.
    """
    marker = disabled.fresh_marker(content)
    enabled = disabled.enable(content, marker)
    if enabled is None:
        # nothing was turned on, so nothing carries a marker to take back off
        return render.render(_formatted(document.parse(content), settings), settings)
    # uncommenting a disabled key can put the same name in the document twice, which no reader
    # reads; the source the caller handed over was read as a document above
    parsed = document.parse_repeating(enabled)
    with disabled.in_use(marker):
        written, spans = render.render_with_spans(_formatted(parsed, settings), settings, marker)
    return disabled.restore(written, spans, marker)


def _formatted(parsed: document.Document, settings: Settings) -> document.Document:
    """Run every rule over the document, in the order they read each other's work."""
    _nest(parsed, settings)
    build_system.fix(parsed, keep_full_version=settings.keep_full_version)
    project.fix(
        parsed,
        keep_full_version=settings.keep_full_version,
        max_supported_python=settings.max_supported_python,
        min_supported_python=settings.min_supported_python,
        generate_python_version_classifiers=settings.generate_python_version_classifiers,
        table_shape=settings.table_shape,
    )
    dependency_groups.fix(parsed, keep_full_version=settings.keep_full_version)
    rules.fix(parsed)
    for tool_fix in (
        poetry.fix,
        setuptools.fix,
        hatch.fix,
        tools.mypy_fix,
        tools.pyright_fix,
        tools.pdm_fix,
        tools.cibuildwheel_fix,
        tools.towncrier_fix,
    ):
        tool_fix(parsed)
    tox.fix(parsed, settings.table_shape, nesting.Width(column=settings.column_width, indent=settings.indent))
    rules.reorder_tables(parsed)
    poetry.reorder_inline_tables_of(parsed)
    tox.reorder_inline_tables_of(parsed)
    setuptools.reorder_inline_tables_of(parsed)
    tools.mypy_reorder_inline_tables(parsed)
    _shape(parsed, settings)
    return parsed


def _nest(parsed: document.Document, settings: Settings) -> None:
    """Fold the tables the settings ask to fold, and write out the ones they ask to keep."""
    shape = settings.table_shape
    width = nesting.Width(column=settings.column_width, indent=settings.indent)
    for name in _nesting_targets(parsed):
        # a setting names a table of any depth, so both passes run over every target: the fold
        # takes the children a setting asks to fold, and the write-out takes the ones it keeps
        nesting.collapse(parsed, name, shape.should_collapse, width)
        nesting.expand(parsed, name, lambda child: not shape.should_collapse(child))


def _nesting_targets(parsed: document.Document) -> list[KeyPath]:
    """Every table that could hold sub-tables: the two fixed roots and each tool that appears."""
    names: list[KeyPath] = [("build-system",), ("project",)]
    seen = set(names)
    for section in parsed.sections:
        # a tool's own name is one segment, whatever it holds
        if len(section.name) > 1 and section.name[0] == "tool":
            head = section.name[:2]
            if head not in seen:
                seen.add(head)
                names.append(head)
    return names


def _shape(parsed: document.Document, settings: Settings) -> None:
    """Wrap what runs past the column, then put the gaps between the tables where they belong."""
    wrapping.wrap_long_strings(parsed, settings.column_width, settings.indent, settings.skip_wrap_for_keys)
    spacing.apply(
        parsed,
        between_groups=settings.separate_root_table.count("\n"),
        within_group=settings.sub_table_spacing.count("\n") if settings.table_format == "long" else None,
    )
