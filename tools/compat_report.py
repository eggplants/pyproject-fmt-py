"""Report where this formatter and the reference implementation write different text.

Output compatibility is not a goal, so this never decides a build. It says how far the two have
drifted and shows the first differing cases, which is how a deliberate divergence is told apart
from a mistake.

Run it against an environment holding both packages::

    uv run --with 'pyproject-fmt==2.29.4' python tools/compat_report.py
"""

from __future__ import annotations

import argparse
import difflib
import importlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterator


class Reference(Protocol):
    """The reference formatter, called with the settings a profile spells out."""

    def __call__(self, text: str, settings: dict[str, Any]) -> str: ...


class Formatter(Protocol):
    """One of the two formatters, already bound to its settings."""

    def __call__(self, text: str) -> str: ...


REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))

import corpus  # noqa: E402  # ty: ignore[unresolved-import]
import profiles  # noqa: E402  # ty: ignore[unresolved-import]

from pyproject_fmt_py import FormatError, Settings, format_toml  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    """Compare both formatters over every corpus case and print what came of it."""
    args = _parse_args(argv)
    reference = _reference()
    cases = corpus.load_all(args.corpus)
    if not cases:
        print(f"no corpus at {args.corpus}; run tools/extract_corpus.py", file=sys.stderr)
        return 1

    same = differs = ours_failed = theirs_failed = 0
    shown = 0
    for case, profile in _pairs(cases):
        settings = profiles.PROFILES[profile]
        theirs = _run(lambda text, s=settings: reference(text, s), case.source)
        ours = _run(lambda text, s=settings: format_toml(text, Settings(**s)), case.source)
        if theirs is None:
            theirs_failed += 1
        if ours is None:
            ours_failed += 1
        if ours is not None and ours == theirs:
            same += 1
            continue
        differs += 1
        if shown < args.show:
            shown += 1
            _show(case, profile, theirs, ours)

    total = same + differs
    share = f"{same / total:.1%}" if total else "n/a"
    print(f"\n{same}/{total} identical ({share})")
    print(f"{ours_failed} rejected here, {theirs_failed} rejected by the reference")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", type=Path, default=REPO / "tests" / "data" / "corpus")
    parser.add_argument("--show", type=int, default=10, help="how many differing cases to print")
    return parser.parse_args(argv)


def _pairs(cases: list[corpus.Case]) -> Iterator[tuple[corpus.Case, str]]:
    for case in cases:
        for profile in case.profiles:
            yield case, profile


def _reference() -> Reference:
    # the reference is supplied by whoever runs this, not by the project, so it is looked up by
    # name rather than imported: nothing here is written against a package this repository holds
    try:
        held = importlib.import_module("pyproject_fmt._lib")
    except ImportError as exc:  # pragma: no cover - the message is the point
        msg = (
            f"install the reference first: uv run --with 'pyproject-fmt==2.29.4' python tools/compat_report.py ({exc})"
        )
        raise SystemExit(msg) from exc
    reference_format, reference_settings = held.format_toml, held.Settings

    def run(text: str, settings: dict[str, Any]) -> str:
        return reference_format(text, reference_settings(**settings))  # type: ignore[no-any-return]

    return run


def _run(call: Formatter, text: str) -> str | None:
    try:
        return call(text)
    except (FormatError, ValueError, NotImplementedError):
        return None


def _show(case: corpus.Case, profile: str, theirs: str | None, ours: str | None) -> None:
    print(f"--- {case.name}@{profile} ({case.origin})")
    if ours is None:
        print("    rejected here")
        return
    if theirs is None:
        print("    rejected by the reference")
        return
    diff = difflib.unified_diff(theirs.splitlines(), ours.splitlines(), "reference", "here", lineterm="", n=1)
    for line in diff:
        print(f"    {line}")


if __name__ == "__main__":
    raise SystemExit(main())
