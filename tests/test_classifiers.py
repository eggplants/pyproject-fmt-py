"""Which Python releases a `requires-python` range admits."""

from __future__ import annotations

import pytest

from pyproject_fmt_py.rules.classifiers import (
    read_specifiers,
    series_holds_a_release,
    supported,
)


def holds(text: str, major: int, minor: int) -> bool:
    clauses = read_specifiers(text)
    assert clauses is not None
    return series_holds_a_release(clauses, major, minor)


@pytest.mark.parametrize(
    ("text", "minor", "held"),
    [
        (">=3.10", 9, False),
        (">=3.10", 10, True),
        (">3.10", 10, True),  # 3.10.1 is above 3.10
        (">3.10.99999", 10, True),
        ("<3.10", 10, False),
        ("<=3.10", 10, True),
        ("<3.11", 10, True),
        ("==3.10.*", 10, True),
        ("==3.10.*", 11, False),
        ("==3.10.1", 10, True),
        ("==3.10.1", 11, False),
        ("!=3.10.*", 10, False),
        ("!=3.10.1", 10, True),
        ("~=3.10", 10, True),
        ("~=3.10", 11, True),
        ("~=3.10", 9, False),
        ("~=3.10.1", 11, False),
        ("===3.10.1", 10, True),
        ("===3.10", 10, False),
        (">=1!3.10", 10, False),
        ("<1!3.10", 10, True),
        (">=3.10,<3.12", 11, True),
        (">=3.10,<3.12", 12, False),
        ("==3.10.0", 10, True),
        ("<3.10.0", 10, False),
        (">=3.10.0a1", 10, True),
    ],
)
def test_says_whether_a_release_of_the_series_fits(text, minor, held):
    assert holds(text, 3, minor) is held


def test_text_that_is_not_a_specifier_set_reads_as_none():
    assert read_specifiers("not a range") is None


def test_a_range_this_cannot_read_says_nothing():
    assert supported("not a range", (3, 13), (3, 9)) is None


def test_nothing_said_leaves_the_configured_window():
    held = supported(None, (3, 12), (3, 10))
    assert held is not None
    assert held.minors == (10, 11, 12)
    assert held.only_python_3
    assert held.write_from == 10


def test_a_lower_bound_gives_the_range_a_floor_of_its_own():
    held = supported(">=3.9", (3, 11), (3, 10))
    assert held is not None
    assert held.minors == (9, 10, 11)
    assert held.write_from == 0


def test_without_a_lower_bound_the_configured_minimum_decides_what_is_written():
    held = supported("<3.12", (3, 13), (3, 10))
    assert held is not None
    assert held.write_from == 10
    assert "Programming Language :: Python :: 3.9" in held.must_have()
    assert "Programming Language :: Python :: 3.9" not in held.worth_writing()


def test_a_range_a_python_2_release_satisfies_is_not_python_3_only():
    held = supported("!=3.0", (3, 11), (3, 10))
    assert held is not None
    assert not held.only_python_3
    assert "Programming Language :: Python :: 3 :: Only" not in held.must_have()


def test_a_range_no_release_satisfies_names_nothing():
    held = supported(">=3.99", (3, 13), (3, 10))
    assert held is not None
    assert held.minors == ()
    assert held.must_have() == set()
