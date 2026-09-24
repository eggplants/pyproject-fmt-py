"""Reading and writing dependencies and versions."""

from __future__ import annotations

import pytest

from pyproject_fmt_py.pep440 import Version, is_valid_version, written_number
from pyproject_fmt_py.pep508 import (
    Marker,
    Requirement,
    VersionOp,
    canonical_name_of,
    names_a_distribution,
)


@pytest.mark.parametrize(
    ("raw", "written"),
    [
        ("1.0.0", "1.0.0"),
        ("v1.2", "1.2"),
        ("1!2.3", "1!2.3"),
        ("1.0a1", "1.0a1"),
        ("1.0alpha1", "1.0a1"),
        ("1.0.beta.2", "1.0b2"),
        ("1.0preview", "1.0rc0"),
        ("1.0-1", "1.0.post1"),
        ("1.0rev", "1.0.post0"),
        ("1.0.dev", "1.0.dev0"),
        ("1.0+A_b-C", "1.0+a.b.c"),
        ("1.0.*", "1.0.*"),
        ("01.002", "1.2"),
    ],
)
def test_reads_a_version(raw, written):
    assert str(Version.parse(raw)) == written


@pytest.mark.parametrize("raw", ["", "not a version", "1.0.0.dev.post.x"])
def test_rejects_text_that_is_not_a_version(raw):
    assert not is_valid_version(raw)
    with pytest.raises(ValueError, match="Invalid version"):
        Version.parse(raw)


def test_drops_the_zeros_a_release_names_nothing_by():
    version = Version.parse("1.0.0.0")
    version.drop_redundant_zeros()
    assert str(version) == "1"


@pytest.mark.parametrize(("digits", "value"), [("0", 0), ("12", 12), ("01", None), ("", None), ("x", None)])
def test_reads_the_digits_pep_440_counts(digits, value):
    assert written_number(digits) == value


@pytest.mark.parametrize(
    ("spec", "written"),
    [
        (">=1.0.0", ">=1.0.0"),
        ("== 1.0", "==1.0"),
        ("~=1.2", "~=1.2"),
        ("===anything+1", "===anything+1"),
        ("!=1.0.*", "!=1.0.*"),
    ],
)
def test_reads_a_specifier(spec, written):
    assert str(VersionOp.parse(spec)) == written


@pytest.mark.parametrize(
    "spec",
    [
        "1.0",  # no operator
        ">=",  # no version
        ">=1.0.*",  # a wildcard follows only == and !=
        "==1.0.*.post1",  # a wildcard follows the release numbers alone
        ">=1.0+local",  # only == and != read a local version
        "~=1",  # a compatible release names at least two numbers
        "===not a version",
    ],
)
def test_rejects_a_clause_pep_440_does_not_put_together(spec):
    with pytest.raises(ValueError, match=r".+"):
        VersionOp.parse(spec)


@pytest.mark.parametrize(
    ("raw", "written"),
    [
        ("a>=1.0.0", "a>=1"),
        ("A_b.C >= 1.0", "a-b-c>=1"),
        ("pkg[Extra,other]>=1", "pkg[Extra,other]>=1"),
        ("pkg (>=1.0, <2)", "pkg>=1,<2"),
        ("pkg>=1.0.0; python_version<'3.9'", "pkg>=1; python_version<'3.9'"),
        ('pkg; python_version >= "3.10"', "pkg; python_version>='3.10'"),
        ("pkg @ https://x/y.zip", "pkg @ https://x/y.zip"),
        ("pkg @ https://x/y.zip ; extra == 'dev'", "pkg @ https://x/y.zip ; extra=='dev'"),
        ("pkg; os_name not in 'nt'", "pkg; os_name not in 'nt'"),
        (
            "pkg; (os_name=='nt' or os_name=='posix') and extra=='dev'",
            "pkg; (os_name=='nt' or os_name=='posix') and extra=='dev'",
        ),
        ('pkg; extra == "it\'s"', 'pkg; extra=="it\'s"'),
        ("pkg[]", "pkg"),
    ],
)
def test_reads_and_writes_a_requirement(raw, written):
    assert str(Requirement.parse(raw).normalize(keep_full_version=False)) == written


def test_keeps_the_full_version_when_asked():
    assert str(Requirement.parse("a>=1.0.0").normalize(keep_full_version=True)) == "a>=1.0.0"


@pytest.mark.parametrize(
    "raw",
    [
        "pkg\nother",  # a requirement is written on one line
        "pkg[unclosed",
        "pkg[not a name]",
        "1pkg-",  # a name opens and closes on a letter or a digit
        "pkg>=1 @ https://x",  # a version and a URL
        "pkg @ ",  # no URL
        "pkg @ https://x y",  # text after the URL
        "pkg (>=1",  # unclosed parenthesis
        "pkg ()",  # no version
        "pkg; python_version",  # no operator
        "pkg; nope == '1'",  # no such marker variable
        "pkg; python_version ~ '1'",  # no such marker operator
        "pkg; (python_version=='3'",  # unclosed group
        "pkg; python_version=='3' extra",  # trailing tokens
        "pkg; python_version=='3' and",  # nothing after the operator
        "pkg; python_version not of '3'",
        "pkg; python_version=='unclosed",
        "pkg; python_version==§",
        "pkg;",
    ],
)
def test_rejects_text_that_is_not_a_requirement(raw):
    with pytest.raises(ValueError, match=r".+"):
        Requirement.parse(raw)


def test_a_name_on_its_own_says_so():
    assert Requirement.parse("pkg").is_name_only
    assert not Requirement.parse("pkg>=1").is_name_only


@pytest.mark.parametrize(
    ("name", "held"),
    [("pkg", True), ("a.b-c_d", True), ("", False), ("-pkg", False), ("pkg-", False), ("pk g", False)],
)
def test_says_what_names_a_distribution(name, held):
    assert names_a_distribution(name) is held


def test_canonicalizes_a_name():
    assert canonical_name_of(" My_Pkg.Name ") == "my-pkg-name"
    with pytest.raises(ValueError, match="Invalid name"):
        canonical_name_of("not a name!")


def test_a_marker_reads_back_as_itself():
    held = Marker.parse("python_version>='3.10' and (os_name=='nt' or extra=='dev')")
    assert str(Marker.parse(str(held))) == str(held)
