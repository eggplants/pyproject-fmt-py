"""The settings the formatter runs under, and how a table's shape is read from them."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from .keys import KeyPath, parse_key_path

if TYPE_CHECKING:
    from collections.abc import Sequence

#: The classifiers this generates name Python 3, so a bound naming another major says nothing it
#: can act on.
PYTHON_MAJOR: Final[int] = 3

TableFormat = str  # "short" | "long"


@dataclass(frozen=True)
class Settings:
    """What a run of the formatter was asked for.

    Attributes:
        column_width: How wide a line may be written, in columns rather than bytes.
        indent: How far a continuation or a nested line is pushed in.
        keep_full_version: Whether a dependency keeps a redundant `.0` in its version.
        max_supported_python: The latest Python release the project supports.
        min_supported_python: The earliest release the generated classifiers may name.
        generate_python_version_classifiers: Whether to derive classifiers from `requires-python`.
        table_format: `short` folds child tables into dotted keys, `long` writes them out.
        sub_table_spacing: The blank lines between the sub-tables of one table, in long form.
        separate_root_table: The blank lines between one root table and the next.
        expand_tables: Tables written out whatever `table_format` says.
        collapse_tables: Tables folded into their parent whatever `table_format` says.
        skip_wrap_for_keys: Keys whose values carry meaning that a line break would obscure.
    """

    column_width: int = 120
    indent: int = 2
    keep_full_version: bool = False
    max_supported_python: tuple[int, int] = (3, 15)
    min_supported_python: tuple[int, int] = (3, 10)
    generate_python_version_classifiers: bool = True
    table_format: TableFormat = "short"
    sub_table_spacing: str = ""
    separate_root_table: str = "\n"
    expand_tables: Sequence[str] = field(default_factory=tuple)
    collapse_tables: Sequence[str] = field(default_factory=tuple)
    skip_wrap_for_keys: Sequence[str] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Reject settings that name something no file can write.

        Raises:
            ValueError: With what the setting says that the formatter cannot act on.
        """
        for name in ("max_supported_python", "min_supported_python"):
            major = getattr(self, name)[0]
            if major != PYTHON_MAJOR:
                msg = f"{name} names Python {major}, and only Python {PYTHON_MAJOR} is supported"
                raise ValueError(msg)
        for name in ("expand_tables", "collapse_tables"):
            for table in getattr(self, name):
                try:
                    parse_key_path(table)
                except ValueError as exc:
                    msg = f"{name}: {table} is not a table name: {exc}"
                    raise ValueError(msg) from exc
        if any(not key.strip() for key in self.skip_wrap_for_keys):
            msg = "skip_wrap_for_keys: a name is written there, not nothing"
            raise ValueError(msg)

    @property
    def table_shape(self) -> TableShape:
        """Which tables fold into their parent under these settings."""
        return TableShape(
            default_collapse=self.table_format == "short",
            expand=frozenset(parse_key_path(name) for name in self.expand_tables),
            collapse=frozenset(parse_key_path(name) for name in self.collapse_tables),
        )


@dataclass(frozen=True)
class TableShape:
    """Which tables fold into their parent.

    Attributes:
        default_collapse: What a table does where no setting names it or anything above it.
        expand: The tables written out, by name.
        collapse: The tables folded in, by name.
    """

    default_collapse: bool
    expand: frozenset[KeyPath]
    collapse: frozenset[KeyPath]

    def should_collapse(self, name: KeyPath) -> bool:
        """Whether the table folds into its parent.

        The closest setting naming the table or one of the tables above it decides. The name is
        compared segment by segment, so a setting cannot cut a quoted name holding a dot in half.
        """
        for depth in range(len(name), 0, -1):
            head = name[:depth]
            if head in self.collapse:
                return True
            if head in self.expand:
                return False
        return self.default_collapse
