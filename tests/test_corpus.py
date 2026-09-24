"""Run the golden corpus: for each case and profile, what the formatter writes is the expectation.

The corpus was seeded from the reference implementation's test sources, but the expectations in it
are this repository's own. Where a rule is deliberately different, edit the case file and say why
in a comment above the section.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest
from conftest import CORPUS, UPDATE_FLAG, read_known_failures
from corpus import Case, load_all
from profiles import PROFILES

from pyproject_fmt_py import FormatError, Settings, format_toml

if TYPE_CHECKING:
    from collections.abc import Iterator

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

CASES = load_all(CORPUS)
KNOWN_FAILURES = read_known_failures()


def _parameters() -> Iterator[tuple[Case, str]]:
    for case in CASES:
        for profile in case.profiles:
            yield case, profile


def _identify(case: Case, profile: str) -> str:
    return f"{case.name}@{profile}"


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Expand every (case, profile) pair, marking the ones not expected to pass yet."""
    if "case" not in metafunc.fixturenames:
        return
    updating = metafunc.config.getoption(UPDATE_FLAG)
    arguments = []
    for case, profile in _parameters():
        case_id = _identify(case, profile)
        marks = [] if updating or case_id not in KNOWN_FAILURES else [pytest.mark.xfail(strict=True)]
        arguments.append(pytest.param(case, profile, id=case_id, marks=marks))
    metafunc.parametrize(("case", "profile"), arguments)


def _reads_as_toml_1_0(source: str) -> bool:
    try:
        tomllib.loads(source)
    except tomllib.TOMLDecodeError:
        return False
    return True


def test_corpus(case: Case, profile: str) -> None:
    """The formatter writes what the case says it writes."""
    settings = Settings(**PROFILES[profile])
    if profile in case.errors:
        with pytest.raises(FormatError) as caught:
            format_toml(case.source, settings)
        assert str(caught.value) == case.errors[profile]
        return

    written = format_toml(case.source, settings)
    assert written == case.outputs[profile]
    # whatever the rules did to it, a result a TOML 1.0 reader accepted going in has to be one
    # coming out; a source using what only TOML 1.1 reads is written back the same way
    if _reads_as_toml_1_0(case.source):
        tomllib.loads(written)
    # running the formatter again has to leave it alone
    assert format_toml(written, settings) == written
