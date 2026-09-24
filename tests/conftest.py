"""Shared test configuration, and the bookkeeping for the corpus' known failures.

The golden corpus is the specification, so every case is expected to pass. The ones that do not
yet are listed in `tests/data/known_failures.txt` and marked `xfail(strict=True)`, which turns a
case that starts passing into a failure until its line is removed. `pytest --update-known-failures`
runs without those marks and rewrites the list from what actually happened.
"""

from __future__ import annotations

from pathlib import Path

import pytest

DATA = Path(__file__).parent / "data"
CORPUS = DATA / "corpus"
KNOWN_FAILURES = DATA / "known_failures.txt"

UPDATE_FLAG = "--update-known-failures"

_HEADER = (
    "# Corpus cases the formatter does not write correctly yet, one <case>@<profile> per line.\n"
    f"# Rewrite with `pytest {UPDATE_FLAG}`.\n"
)
_FAILED = pytest.StashKey[set]()


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add the flag that rewrites the known-failure list from this run."""
    parser.addoption(UPDATE_FLAG, action="store_true", help="rewrite tests/data/known_failures.txt")


def read_known_failures() -> set[str]:
    """The corpus case ids that are not expected to pass yet."""
    if not KNOWN_FAILURES.is_file():
        return set()
    lines = KNOWN_FAILURES.read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def pytest_configure(config: pytest.Config) -> None:
    """Start the tally the update flag writes out."""
    config.stash[_FAILED] = set()


def pytest_report_teststatus(report: pytest.TestReport, config: pytest.Config) -> None:
    """Remember which corpus cases did not pass, so the list can be rewritten from it."""
    if report.when == "call" and "test_corpus" in report.nodeid and report.outcome != "passed":
        config.stash[_FAILED].add(report.nodeid.partition("[")[2].rstrip("]"))


def pytest_sessionfinish(session: pytest.Session) -> None:
    """Write the known-failure list when the run asked for it."""
    if not session.config.getoption(UPDATE_FLAG):
        return
    failed = sorted(session.config.stash[_FAILED])
    KNOWN_FAILURES.parent.mkdir(parents=True, exist_ok=True)
    KNOWN_FAILURES.write_text(_HEADER + "".join(f"{case}\n" for case in failed), encoding="utf-8")


@pytest.fixture(autouse=True, scope="session")
def _corpus_is_present() -> None:
    """Fail loudly rather than silently pass when the corpus has not been generated."""
    if not CORPUS.is_dir():
        pytest.exit(f"no corpus at {CORPUS}; run tools/extract_corpus.py", returncode=1)
