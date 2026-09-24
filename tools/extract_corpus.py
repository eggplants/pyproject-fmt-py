"""Build the golden corpus from the reference implementation's Rust test suite.

The Rust tests carry their sources as `indoc!` blocks and their expectations as `insta` inline
snapshots. Only the sources are taken: several cases run a partial pipeline, so their snapshots
say nothing about what the whole formatter writes. Each source is then run through the reference
implementation under every profile in `tests/profiles.py`, and the result is written out as this
repository's own expectation.

Run it against an environment that holds the reference implementation and nothing of this
package, so the `pyproject-fmt` console script here cannot shadow it::

    uv run --isolated --no-project --with 'pyproject-fmt==2.29.4' \
        python tools/extract_corpus.py

Re-running it overwrites every case, which discards expectations edited by hand. Pass
`--only-missing` to add the cases that are not there yet and leave the rest alone.
"""

from __future__ import annotations

import argparse
import importlib
import re
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))

import corpus  # noqa: E402  # ty: ignore[unresolved-import]
import profiles  # noqa: E402  # ty: ignore[unresolved-import]

DEFAULT_RUST_TESTS = REPO.parent / "toml-fmt" / "pyproject-fmt" / "rust" / "tests"

#: `let start = indoc! {r##"` and `let start = indoc::indoc! {r"`, whose closing delimiter is the
#: quote followed by the same run of hashes. Every `indoc!` bound to a name in that suite is a
#: source; the expectations are `insta` inline snapshots, which this does not read.
_SOURCE = re.compile(r'let [a-z_]+ = (?:indoc::)?indoc! *\{r(#*)"')
_TEST_FN = re.compile(r"^fn (test_[A-Za-z0-9_]+)", re.MULTILINE)
#: Every `indoc!` in the file, to check against what was taken.
_ANY_INDOC = re.compile(r"(?:indoc::)?indoc! *\{")

_INSTALL_FIRST = "install the reference first: uv run --isolated --no-project --with 'pyproject-fmt==2.29.4' python"


class Source(NamedTuple):
    """One document a Rust test formats, and where it was written."""

    module: str
    test: str
    text: str

    @property
    def origin(self) -> str:
        """The Rust test the source was taken from."""
        return f"{self.module}_tests.rs::{self.test}"


def main(argv: list[str] | None = None) -> int:
    """Extract the sources, format them, and write the corpus out."""
    args = _parse_args(argv)
    if not args.rust_tests.is_dir():
        print(f"no Rust test suite at {args.rust_tests}", file=sys.stderr)
        return 1

    sources = list(_sources(args.rust_tests))
    if not sources:
        print(f"no sources found under {args.rust_tests}", file=sys.stderr)
        return 1

    if args.out.exists() and not args.only_missing:
        shutil.rmtree(args.out)

    format_toml, settings_of = _reference()
    written = skipped = 0
    for source in sources:
        name = f"{source.module}/{source.test.removeprefix('test_')}"
        path = corpus.path_of(args.out, name)
        if args.only_missing and path.exists():
            skipped += 1
            continue
        case = corpus.Case(name=name, origin=source.origin, source=source.text)
        for profile in profiles.profiles_for(source.module):
            try:
                case.outputs[profile] = format_toml(source.text, settings_of(profile))
            except ValueError as exc:  # the reference rejects the source, e.g. a bad version
                case.errors[profile] = str(exc)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(corpus.dumps(case), encoding="utf-8")
        written += 1

    print(f"{written} cases written to {args.out}" + (f", {skipped} already there" if skipped else ""))
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rust-tests", type=Path, default=DEFAULT_RUST_TESTS, help="the reference test suite")
    parser.add_argument("--out", type=Path, default=REPO / "tests" / "data" / "corpus", help="where to write cases")
    parser.add_argument("--only-missing", action="store_true", help="keep the cases that are already there")
    return parser.parse_args(argv)


def _reference() -> tuple[Any, Any]:
    """The reference formatter and a way to build its settings for a named profile."""
    # the reference is supplied by whoever runs this, not by the project, so it is looked up by
    # name rather than imported: nothing here is written against a package this repository holds
    try:
        held = importlib.import_module("pyproject_fmt._lib")
    except ImportError as exc:  # pragma: no cover - the message is the point
        msg = f"{_INSTALL_FIRST} tools/extract_corpus.py ({exc})"
        raise SystemExit(msg) from exc

    def settings_of(profile: str) -> object:
        return held.Settings(**profiles.PROFILES[profile])

    return held.format_toml, settings_of


def _sources(root: Path) -> Iterator[Source]:
    """Every source the Rust tests hold, inline or in a file beside them."""
    for path in sorted(root.glob("*_tests.rs")):
        module = path.stem.removesuffix("_tests")
        text = path.read_text(encoding="utf-8")
        taken = 0
        for source in _inline_sources(module, text):
            taken += 1
            yield source
        _report_untaken(path, text, taken)
    for path in sorted((root / "data").glob("*.toml")):
        yield Source(module="data", test=f"test_{path.stem.replace('-', '_')}", text=path.read_text(encoding="utf-8"))


def _inline_sources(module: str, text: str) -> Iterator[Source]:
    ends = [(m.start(), m.group(1)) for m in _TEST_FN.finditer(text)]
    seen: set[str] = set()
    for match in _SOURCE.finditer(text):
        closing = '"' + match.group(1)
        end = text.index(closing, match.end())
        test = next((name for start, name in reversed(ends) if start < match.start()), "test_unnamed")
        # a test may format more than one source; the later ones get a suffix of their own
        name, count = test, 1
        while name in seen:
            count += 1
            name = f"{test}_{count}"
        seen.add(name)
        yield Source(module=module, test=name, text=_unindent(text[match.end() : end]))


def _report_untaken(path: Path, text: str, taken: int) -> None:
    """Say where a file holds `indoc!` blocks the pattern above did not reach."""
    total = len(_ANY_INDOC.findall(text))
    if total > taken:
        print(f"{path.name}: {total - taken} of {total} indoc! blocks not taken", file=sys.stderr)


def _unindent(literal: str) -> str:
    """What `indoc!` makes of a raw string: drop the opening line, strip the common indent."""
    lines = literal.split("\n")
    if lines and not lines[0].strip():
        lines = lines[1:]
    widths = [len(line) - len(line.lstrip(" ")) for line in lines if line.strip()]
    pad = min(widths, default=0)
    return "\n".join(line[pad:] if line.strip() else "" for line in lines)


if __name__ == "__main__":
    raise SystemExit(main())
