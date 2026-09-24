"""The `[tool.tox]` table.

Every rule here finds an environment by its own header, and the short format has already folded
each one into `[tool.tox]`. Writing them back out is what lets one set of rules serve both formats,
and lets `[tool.tox]` say what a standalone `tox.toml` says.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..arrays import map_strings, sort, sort_names_in, sort_placed, sort_strings, text_of
from ..disabled import is_enabled_here
from ..document import Array, Entry, InlineTable, Scalar
from ..keys import dotted_name, render_segment
from ..nesting import Width, collapse, expand
from ..ordering import reorder_keys
from ..pep508 import Requirement
from ..sections import (
    InlineSchema,
    every_value,
    for_entry_runs,
    for_key_paths_under,
    for_keys_under,
    for_names_under,
    for_value_at,
    rename_tables_of,
    rename_under,
    reorder_inline_tables,
    reorder_tables_of,
)
from ..sorting import natural_lexical_key
from ._data import (
    TOX_ENV_ALIASES,
    TOX_ENV_KEY_ORDER,
    TOX_ROOT_ALIASES,
    TOX_ROOT_KEY_ORDER,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..config import TableShape
    from ..document import Document, Member, Value
    from ..keys import KeyPath

PATH: KeyPath = ("tool", "tox")

#: tox reads a `set_env` table in the order it is written: a key after `file` overrides what that
#: file said, and one before it does not.
KEEP_ORDER = ("set_env",)

#: The tables a base environment is named by, which carry one segment rather than two.
_BASE_ENVS = ("env_run_base", "env_pkg_base")

#: The tables whose next segment names the environment.
_NAMED_ENVS = ("env", "env_base")

#: The inline tables tox writes, each recognized by a key only it carries.
INLINE_SCHEMAS: tuple[InlineSchema, ...] = (
    InlineSchema(
        "replace",
        (
            "replace",
            "condition",
            "of",
            "env",
            "key",
            "name",
            "pattern",
            "then",
            "else",
            "default",
            "extend",
            "marker",
        ),
    ),
    InlineSchema("prefix", ("prefix", "start", "stop")),
    InlineSchema("product", ("product", "exclude")),
    InlineSchema("value", ("value", "marker")),
)


def fix(document: Document, table_shape: TableShape, width: Width) -> None:
    """Normalize the aliases, the environments and the root table, in that order."""
    if not _holds_tox(document):
        return
    folded = table_shape.should_collapse(PATH)
    if folded:
        expand(document, PATH, lambda _name: True)
        for name in ("env", "env_base"):
            expand(document, (*PATH, name), lambda _name: True)
    _normalize_aliases(document)
    _fix_envs(document)
    # a folded environment is a run of keys of `[tool.tox]`, so it takes its place in that table's
    # order only once it is folded back
    if folded:
        collapse(document, PATH, table_shape.should_collapse, width)
    _fix_root(document)
    _sort_env_list(document)


def reorder_inline_tables_of(document: Document) -> None:
    """Order the inline tables the schemas recognize."""
    reorder_inline_tables(document, PATH, INLINE_SCHEMAS)


def _holds_tox(document: Document) -> bool:
    """Whether the file says anything under `tool.tox`, wherever it split the path."""
    if any(len(section.name) >= len(PATH) and section.name[: len(PATH)] == PATH for section in document.sections):
        return True
    held: list[Entry] = []
    for_names_under(document, PATH, lambda _tail, entry: held.append(entry))
    return bool(held)


def _env_table_of(name: KeyPath) -> KeyPath | None:
    """The environment table the path names or sits under, where it names one at all.

    The check counts segments rather than dots, since an environment may be named anything:
    `[env.".pkg-cpython311"]` is one environment, not a table two levels down.
    """
    if len(name) < len(PATH) or name[: len(PATH)] != PATH:
        return None
    tail = name[len(PATH) :]
    if tail[:1] and tail[0] in _BASE_ENVS:
        held = 1
    elif len(tail) >= 2 and tail[0] in _NAMED_ENVS:  # noqa: PLR2004 - the table then its name
        held = 2
    else:
        return None
    return name[: len(PATH) + held]


def _normalize_aliases(document: Document) -> None:
    """Write every key tox renamed under the name tox documents, references included."""
    renamed = [(PATH, held, to) for held, to in rename_under(document, PATH, TOX_ROOT_ALIASES)]
    renamed += rename_tables_of(document, _env_table_of, TOX_ENV_ALIASES)
    # a `{ replace = "ref" }` names a key rather than holding text that looks like one, so a key
    # that moved takes the references to it along
    for value in every_value(document):
        _follow_renames(value, renamed)


def _follow_renames(value: Value, renamed: Sequence[tuple[KeyPath, str, str]]) -> None:
    if isinstance(value, Array):
        for member in value.members:
            _follow_renames(member.value, renamed)
        return
    if not isinstance(value, InlineTable):
        return
    for entry in value.entries:
        _follow_renames(entry.value, renamed)
    if not _names_a_reference(value):
        return
    for entry in value.entries:
        if dotted_name(entry.key) == "of" and isinstance(entry.value, Array):
            _rename_in_path(entry.value, renamed)


def _names_a_reference(table: InlineTable) -> bool:
    """Whether the inline table is one of tox's `replace = "ref"` substitutions."""
    return any(
        dotted_name(entry.key) == "replace"
        and isinstance(entry.value, Scalar)
        and entry.value.kind == "string"
        and entry.value.text == "ref"
        for entry in table.entries
    )


def _rename_in_path(path: Array, renamed: Sequence[tuple[KeyPath, str, str]]) -> None:
    """The last segment of a reference path is the key it names; the ones before name the table."""
    named = [text for member in path.members if (text := text_of(member)) is not None]
    if len(named) != len(path.members) or not named:
        return
    key, table = named[-1], tuple(named[:-1])
    for held, held_from, held_to in renamed:
        if held_from == key and _names_the_same_table(held, table):
            path.members[-1].value = Scalar.of_string(held_to)
            return


def _names_the_same_table(held: KeyPath, table: KeyPath) -> bool:
    """Whether the reference names the table the rename happened in, prefix or no prefix.

    Any other tail is a different table: an environment named `src` is not the root table of that
    name.
    """
    return held == table or (held[: len(PATH)] == PATH and held[len(PATH) :] == table)


def _fix_root(document: Document) -> None:
    for_keys_under(document, PATH, _normalize_requires)
    names: list[KeyPath] = []
    for_names_under(document, PATH, lambda tail, _entry: names.append(tail))
    order = root_key_order(names)

    def order_the_root(entries: list[Entry], under: KeyPath) -> None:
        # the root table is the run of keys the file wrote for it; an environment below it is a
        # table of its own, which its own rules order
        if under == PATH:
            reorder_keys(entries, order)

    for_entry_runs(document, PATH, order_the_root)


def _normalize_requires(key: str, value: Value) -> None:
    if key == "requires":
        _normalize_and_sort_requirements(value)


def root_key_order(names: Sequence[KeyPath]) -> tuple[str, ...]:
    """The root key order, with a slot for every key of an environment folded into the table."""
    order = list(TOX_ROOT_KEY_ORDER)
    for group in _folded_env_names(names):
        order += [f"{group}.{key}" for key in TOX_ENV_KEY_ORDER if key]
        order.append(group)
    return tuple(order)


def _folded_env_names(names: Sequence[KeyPath]) -> list[str]:
    """The environments a table holds as dotted keys, each named the way its keys name it."""
    held: list[str] = []
    for tail in names:
        if len(tail) >= 2 and tail[0] in _BASE_ENVS:  # noqa: PLR2004 - the table then one of its keys
            name = tail[0]
        elif len(tail) >= 3 and tail[0] in _NAMED_ENVS:  # noqa: PLR2004 - the table, its name, a key
            name = f"{tail[0]}.{render_segment(tail[1])}"
        else:
            continue
        if name not in held:
            held.append(name)
    return sorted(held)


def _fix_envs(document: Document) -> None:
    _upgrade_use_develop(document)
    # one walk of the file serves every environment in it, whichever one each key belongs to

    def visit(named: KeyPath, entry: Entry) -> None:
        env = _env_table_of(named)
        if env is not None and len(named) > len(env):
            _fix_env_entry(dotted_name(named[len(env) :]), entry.value)

    for_key_paths_under(document, PATH, visit)
    reorder_tables_of(document, _env_table_of, TOX_ENV_KEY_ORDER, KEEP_ORDER)


def _fix_env_entry(key: str, value: Value) -> None:
    if key == "deps":
        _normalize_and_sort_requirements(value)
    elif key in {"dependency_groups", "allowlist_externals", "extras", "labels", "depends"}:
        sort_names_in(value)
    elif key == "pass_env":
        _sort_pass_env(value)
    # each constraint is the path or URL of a file tox hands to pip, not a requirement


def _sort_pass_env(value: Value) -> None:
    """Inline tables lead, then the plain names alphabetically."""
    if not isinstance(value, Array):
        return

    def key_of(member: Member) -> tuple[int, object] | None:
        if isinstance(member.value, InlineTable):
            return 0, natural_lexical_key("")
        text = text_of(member)
        return None if text is None else (1, natural_lexical_key(text.lower()))

    sort(value, key_of)


def _sort_env_list(document: Document) -> None:
    """Put `env_list` in the order the formatter writes one.

    CPython versions come first, newest first; then PyPy versions, newest first; then everything
    else by name. A compound name is placed by the first part of it that reads as one of those. An
    entry that generates environments rather than naming one holds the place the file gave it.
    """

    def in_list(value: Value) -> None:
        if isinstance(value, Array):
            sort_placed(value, _ranked_env)

    for_value_at(document, (*PATH, "env_list"), in_list)


def _ranked_env(member: Member) -> tuple[int, int, int, object] | None:
    """Where a name sits in the list, or None where the entry names no one environment."""
    text = text_of(member)
    if text is None:
        return None
    named = text.lower()
    for part in named.split("-"):
        held = _interpreter(part)
        if held is not None:
            kind, major, minor = held
            return kind, major, minor, natural_lexical_key(named)
    return 3, 0, 0, natural_lexical_key(named)


def _interpreter(part: str) -> tuple[int, int, int] | None:
    """The interpreter a name part spells, with its version negated so the newest sorts first."""
    if part.startswith("pypy"):
        kind, version = 2, part.removeprefix("pypy")
    else:
        kind, version = 1, part.removeprefix("py")
    # `py312` and `py3.12` both name a version, and a name holding anything else names none
    major, _, minor = version.partition(".")
    if not major or not (major + minor).isdigit():
        return None
    return kind, -int(major), -int(minor or 0)


def _upgrade_use_develop(document: Document) -> None:
    """`use_develop = true` says what `package = "editable"` says, which is what tox documents."""

    def in_run(entries: list[Entry], under: KeyPath) -> None:
        held: list[KeyPath] = []
        for entry in entries:
            env = _env_table_of((*under, *entry.key))
            if env is None or env[: len(under)] != under:
                continue
            head = env[len(under) :]
            if head not in held:
                held.append(head)
        for head in held:
            _upgrade_one(entries, head)

    for_entry_runs(document, (), in_run)


def _upgrade_one(entries: list[Entry], head: KeyPath) -> None:
    def names(entry: Entry, name: str) -> bool:
        return entry.key == (*head, name)

    # a disabled key is one the comment beside it speaks for: migrating it would leave that comment
    # on a key the file wrote
    at = next(
        (
            index
            for index, entry in enumerate(entries)
            if names(entry, "use_develop") and _is_true(entry.value) and not is_enabled_here(entry)
        ),
        None,
    )
    if at is None:
        return
    # a key the file wrote as a comment reserves no name
    active = [entry for entry in entries if not is_enabled_here(entry)]
    package = next((entry for entry in active if names(entry, "package")), None)
    removed = entries.pop(at)
    if package is not None:
        # the comments around the older key are about the environment, so they move to the key that
        # says the same thing; two comments cannot share one line, so the older one takes a line
        package.value = Scalar.of_string("editable")
        package.lead[:0] = removed.lead
        if removed.comment is not None:
            if package.comment is None:
                package.comment = removed.comment
            else:
                package.lead.append(removed.comment)
        return
    # the key keeps whatever path the file wrote it under, so it stays the same environment's
    entries.insert(
        at,
        Entry(
            key=(*head, "package"),
            value=Scalar.of_string("editable"),
            lead=removed.lead,
            comment=removed.comment,
        ),
    )


def _is_true(value: Value) -> bool:
    """Whether the value is the boolean `true`, rather than text written with those letters."""
    return isinstance(value, Scalar) and value.kind == "bool" and value.raw == "true"


def _normalize_and_sort_requirements(value: Value) -> None:
    if not isinstance(value, Array):
        return
    # a requirement this parser cannot read is left as the file wrote it
    map_strings(value, _normalized)
    # pip reads this list the way it reads a requirements file, where a later `--index-url`
    # replaces the one before it, so a list holding anything else keeps the order it names them in
    if all(_reads_as_a_requirement(member) for member in value.members):
        sort_strings(value, lambda text: natural_lexical_key(_sort_name(text)))


def _normalized(text: str) -> str:
    if _should_skip(text):
        return text
    try:
        return str(Requirement.parse(text).normalize(keep_full_version=False))
    except ValueError:
        return text


def _sort_name(text: str) -> str:
    try:
        return Requirement.parse(text).canonical_name
    except ValueError:
        return text.lower()


def _reads_as_a_requirement(member: Member) -> bool:
    """Whether the member is a requirement rather than a line pip reads as something else."""
    text = text_of(member)
    if text is None or _should_skip(text):
        return False
    try:
        Requirement.parse(text)
    except ValueError:
        return False
    return True


def _should_skip(text: str) -> bool:
    """Whether the text names a file, a path or a templated value rather than a requirement."""
    if text.startswith(("-", "./", "../", "/")) or "{" in text or "://" in text:
        return True
    lowered = text.lower()
    return lowered.endswith((".whl", ".zip", ".tar.gz", ".tar.bz2", ".tar.xz", ".tar.z", ".tgz"))
