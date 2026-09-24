"""Reading the settings a file holds for the formatter.

A `pyproject.toml` carries its own under `[tool.pyproject-fmt]`, and a project may keep shared ones
in a `pyproject-fmt.toml` beside it. Both are read the same way: the table the caller names, with
each of its scalar keys as the setting it spells.
"""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:
    from collections.abc import Sequence

#: A value a settings table holds, in the forms a setting is written in.
SettingValue: TypeAlias = "str | int | bool | list[SettingValue] | dict[str, SettingValue]"


def settings_in(content: str, path: Sequence[str] = ()) -> dict[str, SettingValue] | None:
    """The settings the table `path` names, or None where the file writes no such table.

    Args:
        content: The text of the file.
        path: The table to read, or the empty path for the whole file.

    Returns:
        What the table says, or None where there is no such table.

    Raises:
        SyntaxError: If the text is not a TOML document.
        TypeError: If the name the path gives holds something other than a table.
    """
    try:
        held: SettingValue = tomllib.loads(content)
    except tomllib.TOMLDecodeError as exc:
        raise SyntaxError(str(exc)) from exc
    for segment in path:
        if not isinstance(held, dict):
            msg = f"{segment}: is written under something that is not a table"
            raise TypeError(msg)
        if segment not in held:
            return None
        held = held[segment]
    if not isinstance(held, dict):
        msg = f"{'.'.join(path)}: is not a table"
        raise TypeError(msg)
    return held
