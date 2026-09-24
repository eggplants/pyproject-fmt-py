"""The corpus file format has to survive a round trip, or the goldens say the wrong thing."""

from __future__ import annotations

import pytest
from conftest import CORPUS
from corpus import Case, dumps, load_all, loads, path_of


def _round_trip(case: Case) -> Case:
    return loads(dumps(case), case.name)


def test_round_trips_a_case_with_outputs_and_errors():
    case = Case(
        name="a/b",
        origin="x_tests.rs::test_y",
        source='[project]\nname = "x"\n',
        outputs={"short": "[project]\n", "long": "[project]\n"},
        errors={"narrow": "project.version is invalid"},
    )
    assert _round_trip(case) == case


def test_round_trips_an_empty_source():
    case = Case(name="a/b", origin="o", source="", outputs={"short": ""})
    assert _round_trip(case) == case


def test_round_trips_a_body_without_a_final_newline():
    case = Case(name="a/b", origin="o", source="a = 1", outputs={"short": "a = 1"})
    assert _round_trip(case) == case


def test_refuses_a_body_holding_a_delimiter():
    case = Case(name="a/b", origin="o", source="%%% input -\n")
    with pytest.raises(ValueError, match="cannot hold a line starting with"):
        dumps(case)


def test_path_of_maps_a_name_to_a_file():
    assert path_of(CORPUS, "project/name").name == "name.txt"
    assert path_of(CORPUS, "project/name").parent.name == "project"


def test_every_stored_case_round_trips():
    for case in load_all(CORPUS):
        assert _round_trip(case) == case, case.name


def test_every_stored_case_says_something():
    for case in load_all(CORPUS):
        assert case.origin, case.name
        assert case.profiles, case.name
