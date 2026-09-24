"""The `pyproject-fmt` command line.

One option set is built per input: the flags the command line wrote, then a shared
`pyproject-fmt.toml` found beside the file, then the `[tool.pyproject-fmt]` table the file itself
holds. What is written closer to the file wins.
"""

from __future__ import annotations

import difflib
import os
import sys
from argparse import Action, ArgumentDefaultsHelpFormatter, ArgumentParser, ArgumentTypeError, Namespace
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from . import __version__
from .config import PYTHON_MAJOR, Settings
from .errors import FormatError
from .formatter import format_toml
from .settings_file import settings_in

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Sequence

    from .settings_file import SettingValue

#: What the file this formats is called, which a directory argument is read as.
FILENAME: Final[str] = "pyproject.toml"

PROG: Final[str] = "pyproject-fmt"

#: The keys that say how the run goes rather than how a file is written.
_RUN_KEYS: Final[frozenset[str]] = frozenset({"inputs", "stdout", "check", "no_print_diff", "config"})

#: A larger count asks the formatter for a string no line can hold.
_COUNT_LIMIT: Final[int] = 10_000

_MINOR_LIMIT: Final[int] = 255
_MIN_SUPPORTED_PYTHON: Final[tuple[int, int]] = (PYTHON_MAJOR, 10)

_GREEN: Final[str] = "\u001b[32m"
_RED: Final[str] = "\u001b[31m"
_RESET: Final[str] = "\u001b[0m"


def count_argument(value: object) -> int:
    """Read a count, rejecting booleans and anything outside 0 through 10,000.

    Raises:
        ArgumentTypeError: With why the text names no count.
    """
    # `True` is an integer to Python, and a file that writes one there names no count
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        msg = f"invalid count: {value!r}"
        raise ArgumentTypeError(msg)
    try:
        count = int(value)
    except ValueError as exc:
        msg = f"invalid count: {value!r} due {exc!r}"
        raise ArgumentTypeError(msg) from exc
    if count < 0:
        msg = f"invalid count: {count}, must not be negative"
        raise ArgumentTypeError(msg)
    if count > _COUNT_LIMIT:
        msg = f"invalid count: {count}, must be at most {_COUNT_LIMIT}"
        raise ArgumentTypeError(msg)
    return count


def spacing_argument(value: object) -> str:
    r"""Read a run of blank lines, which a TOML setting may spell as `\n`.

    Raises:
        ArgumentTypeError: If the value is not text.
    """
    if not isinstance(value, str):
        msg = f"invalid spacing: {value!r}"
        raise ArgumentTypeError(msg)
    return value.replace("\\n", "\n")


def list_argument(value: object) -> list[str]:
    """Read a comma-separated list from the command line, or a string array from a file.

    Raises:
        ArgumentTypeError: If the value is not a list of names.
    """
    if isinstance(value, str):
        return [name for part in _split_outside_quotes(value) if (name := part.strip())]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    msg = f"invalid list: {value!r}, every entry names one thing"
    raise ArgumentTypeError(msg)


def version_argument(got: object) -> tuple[int, int]:
    """Read a `major.minor` Python version.

    Raises:
        ArgumentTypeError: With why the text names no supported Python release.
    """
    if not isinstance(got, str):
        msg = f"invalid version: {got!r}, must be e.g. 3.14"
        raise ArgumentTypeError(msg)
    try:
        major_text, minor_text = got.split(".")
        major, minor = int(major_text), int(minor_text)
    except ValueError as exc:
        msg = f"invalid version: {got}, must be e.g. 3.14"
        raise ArgumentTypeError(msg) from exc
    # the classifiers this generates name Python 3, and the formatter holds a minor as a byte
    if major != PYTHON_MAJOR or not 0 <= minor <= _MINOR_LIMIT:
        msg = f"invalid version: {got}, must name a Python {PYTHON_MAJOR} minor from 3.0 to 3.{_MINOR_LIMIT}"
        raise ArgumentTypeError(msg)
    # a window that ends before it starts names no release and would empty the classifier set
    if (major, minor) < _MIN_SUPPORTED_PYTHON:
        msg = f"invalid version: {got}, must not precede {_MIN_SUPPORTED_PYTHON[0]}.{_MIN_SUPPORTED_PYTHON[1]}"
        raise ArgumentTypeError(msg)
    return major, minor


@dataclass(frozen=True)
class Setting:
    """One formatting setting, named once for the command line and for the file that may hold it.

    Attributes:
        flag: What the command line calls it.
        help: What the help text says about it.
        takes: What a file may write there.
        default: What it is where nothing names it.
        convert: How the text is read, on the command line and in a file alike.
        choices: The values it accepts, where it accepts only some.
        metavar: What the help text calls its argument.
    """

    flag: str
    help: str
    takes: type
    default: object
    convert: Callable[[object], object] | None = None
    choices: tuple[str, ...] | None = None
    metavar: str | None = None
    action: str | None = None

    @property
    def name(self) -> str:
        """The setting's name, which is what argparse and a settings table both spell it as."""
        return self.flag.removeprefix("--no-").removeprefix("--").replace("-", "_")


#: One declaration keeps the command line and the settings a file holds under the same constraints.
SETTINGS: Final[tuple[Setting, ...]] = (
    Setting("--column-width", "max column width in the TOML file", int, 120, count_argument, metavar="count"),
    Setting("--indent", "number of spaces to use for indentation", int, 2, count_argument, metavar="count"),
    Setting(
        "--table-format",
        "table format: 'short' collapses sub-tables, 'long' expands to [table.subtable]",
        str,
        "short",
        choices=("short", "long"),
    ),
    Setting(
        "--sub-table-spacing",
        r"extra newlines between sub-tables in the same group (e.g. '\n' for one blank line)",
        str,
        "",
        spacing_argument,
    ),
    Setting(
        "--separate-root-table",
        r"extra newlines between root table groups (e.g. '\n' for one blank line)",
        str,
        "\n",
        spacing_argument,
    ),
    Setting("--expand-tables", "comma-separated list of tables to force expand", list, [], list_argument),
    Setting("--collapse-tables", "comma-separated list of tables to force collapse", list, [], list_argument),
    Setting(
        "--skip-wrap-for-keys",
        "comma-separated key patterns to skip string wrapping (wildcards like '*.parse' are read)",
        list,
        [],
        list_argument,
    ),
    Setting(
        flag="--keep-full-version",
        help="retain redundant .0 components in dependency versions",
        takes=bool,
        default=False,
        action="store_true",
    ),
    Setting(
        "--max-supported-python",
        "latest Python version the project supports (e.g. 3.14)",
        str,
        (3, 15),
        version_argument,
        metavar="major.minor",
    ),
    Setting(
        flag="--no-generate-python-version-classifiers",
        help="retain Python version classifiers instead of deriving them from requires-python",
        takes=bool,
        default=True,
        action="store_false",
    ),
)


def build_parser() -> ArgumentParser:
    """Build the parser without reading arguments, for documentation tooling."""
    return _make_parser()[0]


def main(args: Sequence[str] | None = None) -> int:
    """Format every input named on the command line.

    Args:
        args: Arguments to read instead of `sys.argv[1:]`, for embedding and for the tests.

    Returns:
        1 after a change or a rejection, and 0 when every input was already formatted.
    """
    parser, actions = _make_parser()
    opt = parser.parse_args(args)
    if opt.config is not None and not opt.config.is_file():
        parser.error(f"config file does not exist: {opt.config}")
    _check_write_permission(parser, opt)
    held = [_read_one(parser, opt, actions, path) for path in opt.inputs]
    return int(any(_write_one(one) for one in held))


@dataclass(frozen=True)
class _Input:
    """One file to format, with the settings it is formatted under."""

    path: Path | None
    source: str
    ending: str
    opt: Namespace


def _make_parser() -> tuple[ArgumentParser, list[Action]]:
    parser = ArgumentParser(formatter_class=ArgumentDefaultsHelpFormatter, prog=PROG)
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s ({__version__})")

    mode_group = parser.add_argument_group("run mode")
    mode = mode_group.add_mutually_exclusive_group()
    mode.add_argument("-s", "--stdout", action="store_true", help="write formatted TOML to stdout")
    mode.add_argument("--check", action="store_true", help="fail when an input needs formatting")
    mode_group.add_argument("-n", "--no-print-diff", action="store_true", help="suppress diffs in check mode")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="path",
        help=f"path to a shared {PROG}.toml config file",
    )

    group = parser.add_argument_group("formatting behavior")
    actions: list[Action] = [_add_setting(group, setting) for setting in SETTINGS]
    parser.add_argument(
        "inputs",
        nargs="+",
        type=_input_path,
        help=f"{FILENAME} file(s) to format, use '-' to read from stdin",
    )
    return parser, actions


def _add_setting(group: Any, setting: Setting) -> Action:  # noqa: ANN401 - argparse names no group type
    held: dict[str, Any] = {"default": setting.default, "help": setting.help, "dest": setting.name}
    if setting.action is not None:
        held["action"] = setting.action
    else:
        held["type"] = setting.convert
        if setting.choices is not None:
            held["choices"] = list(setting.choices)
        if setting.metavar is not None:
            held["metavar"] = setting.metavar
    return group.add_argument(setting.flag, **held)


def _input_path(argument: str) -> Path | None:
    """The file an argument names, or None where it asks for standard input.

    Raises:
        ArgumentTypeError: With why the path names nothing this can format.
    """
    if argument == "-":
        return None
    path = Path(argument).absolute()
    if path.is_dir():
        path /= FILENAME
    if not path.exists():
        msg = "path does not exist"
        raise ArgumentTypeError(msg)
    if not path.is_file():
        msg = "path is not a file"
        raise ArgumentTypeError(msg)
    if not os.access(path, os.R_OK):
        msg = "cannot read path"
        raise ArgumentTypeError(msg)
    return path


def _check_write_permission(parser: ArgumentParser, opt: Namespace) -> None:
    if opt.stdout or opt.check:
        return
    for path in opt.inputs:
        if path is not None and not os.access(path, os.W_OK):
            parser.error(f"argument inputs: cannot write path {path}")


def _read_one(parser: ArgumentParser, opt: Namespace, actions: Sequence[Action], path: Path | None) -> _Input:
    source, ending = _read_source(parser, path)
    named = _display_name(path)
    held = Namespace(**vars(opt))
    if opt.config is not None:
        _apply(parser, held, _shared_settings(parser, opt.config), str(opt.config), actions)
    elif (found := _find_config(path.parent if path is not None else Path.cwd())) is not None:
        _apply(parser, held, _shared_settings(parser, found), str(found), actions)
    try:
        # the formatter reads the same source next and reports on it in its own words, against the
        # file rather than against one setting
        own = settings_in(source, ("tool", PROG))
    except SyntaxError:
        own = None
    except (TypeError, ValueError) as exc:
        parser.error(f"{named}: {exc}")
    if own is not None:
        _apply(parser, held, own, named, actions)
    return _Input(path=path, source=source, ending=ending, opt=held)


def _read_source(parser: ArgumentParser, path: Path | None) -> tuple[str, str]:
    if path is None:
        return sys.stdin.read(), "\n"
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            raw = handle.read()
    except UnicodeDecodeError as exc:
        parser.error(f"{path}: {exc}")
    crlf = raw.count("\r\n")
    # a mixed file gets the ending it uses most, ties going to the line feed
    return raw.replace("\r\n", "\n"), "\r\n" if crlf > raw.count("\n") - crlf else "\n"


def _find_config(start: Path) -> Path | None:
    """The shared config file written beside the input, or above it."""
    current = start.resolve()
    while True:
        if (candidate := current / f"{PROG}.toml").is_file():
            return candidate
        if (parent := current.parent) == current:
            return None
        current = parent


def _shared_settings(parser: ArgumentParser, path: Path) -> dict[str, SettingValue]:
    try:
        return settings_in(path.read_text(encoding="utf-8")) or {}
    except (SyntaxError, TypeError, ValueError, UnicodeDecodeError) as exc:
        parser.error(f"{path}: {exc}")


def _apply(
    parser: ArgumentParser,
    opt: Namespace,
    config: dict[str, SettingValue],
    source: str,
    actions: Sequence[Action],
) -> None:
    """Put the settings a file holds over the ones already read, refusing what it cannot say."""
    by_name = {setting.name: setting for setting in SETTINGS}
    allowed = {action.dest: action.choices for action in actions if action.choices}
    for key, raw in config.items():
        setting = by_name.get(key)
        if setting is None or key in _RUN_KEYS:
            parser.error(f"{source}: {key}: unknown setting")
        # Python treats `True` as an integer; a flag reads no other one
        if not isinstance(raw, setting.takes) or (setting.takes is not bool and isinstance(raw, bool)):
            parser.error(f"{source}: {key}: {raw!r} is not written as {setting.takes.__name__}")
        value: object = raw
        if setting.convert is not None:
            try:
                value = setting.convert(raw)
            except (ArgumentTypeError, TypeError, ValueError) as exc:
                parser.error(f"{source}: {key}: {exc}")
        if key in allowed and value not in (allowed[key] or ()):
            choices = ", ".join(repr(choice) for choice in allowed[key] or ())
            parser.error(f"{source}: {key}: invalid choice: {value!r} (choose from {choices})")
        setattr(opt, key, value)


def _settings_of(opt: Namespace) -> Settings:
    return Settings(
        column_width=opt.column_width,
        indent=opt.indent,
        keep_full_version=opt.keep_full_version,
        max_supported_python=opt.max_supported_python,
        min_supported_python=_MIN_SUPPORTED_PYTHON,
        generate_python_version_classifiers=opt.generate_python_version_classifiers,
        table_format=opt.table_format,
        sub_table_spacing=opt.sub_table_spacing,
        separate_root_table=opt.separate_root_table,
        expand_tables=opt.expand_tables,
        collapse_tables=opt.collapse_tables,
        skip_wrap_for_keys=opt.skip_wrap_for_keys,
    )


def _write_one(held: _Input) -> bool:
    """Format one input and say whether it changed or was refused."""
    named = _display_name(held.path)
    try:
        formatted = format_toml(held.source, _settings_of(held.opt))
    except (FormatError, ValueError) as exc:
        print(f"{named}: {exc}", file=sys.stderr)
        return True
    changed = held.source != formatted
    if held.path is None or held.opt.stdout:
        print(formatted, end="")
        return changed
    if changed and not held.opt.check:
        held.path.write_text(formatted, encoding="utf-8", newline=held.ending)
    if held.opt.no_print_diff:
        return changed
    if changed:
        diff = difflib.unified_diff(held.source.splitlines(), formatted.splitlines(), fromfile=named, tofile=named)
        print("\n".join(_coloured(diff)))
    else:
        print(f"no change for {named}")
    return changed


def _display_name(path: Path | None) -> str:
    if path is None:
        return "<stdin>"
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def _coloured(diff: Iterable[str]) -> Iterator[str]:
    if "NO_COLOR" in os.environ:  # https://no-color.org
        yield from diff
        return
    for line in diff:
        if line.startswith("+"):
            yield f"{_GREEN}{line}{_RESET}"
        elif line.startswith("-"):
            yield f"{_RED}{line}{_RESET}"
        else:
            yield line


def _split_outside_quotes(value: str) -> Iterator[str]:
    """Split on the commas between names, since a name TOML quotes may hold one of its own."""
    quote: str | None = None
    escaped = False
    start = 0
    for at, character in enumerate(value):
        if quote is not None:
            if escaped:
                escaped = False
            elif quote == '"' and character == "\\":
                escaped = True
            elif character == quote:
                quote = None
        elif character in {'"', "'"}:
            quote = character
        elif character == ",":
            yield value[start:at]
            start = at + 1
    yield value[start:]


if __name__ == "__main__":
    raise SystemExit(main())
