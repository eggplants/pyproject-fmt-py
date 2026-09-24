"""The command line: what it reads, where it writes, and what it says about a change."""

from __future__ import annotations

import pytest

from pyproject_fmt_py import __version__
from pyproject_fmt_py.cli import build_parser, main

UNFORMATTED = '[project]\nname="My_Pkg"\ndependencies=["b","a>=1.0.0"]\n'
FORMATTED = '[project]\nname = "my-pkg"\ndependencies = [ "a>=1", "b" ]\n'

NO_CLASSIFIERS = "[tool.pyproject-fmt]\ngenerate_python_version_classifiers = false\n"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NO_COLOR", "1")
    path = tmp_path / "pyproject.toml"
    path.write_text(UNFORMATTED + NO_CLASSIFIERS, encoding="utf-8")
    return path


def test_version_flag_prints_the_version(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["--version"])
    assert caught.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_builds_the_parser_without_reading_arguments():
    assert build_parser().prog == "pyproject-fmt"


def test_writes_the_file_and_says_it_changed(project, capsys):
    assert main([str(project)]) == 1
    assert project.read_text(encoding="utf-8").startswith(FORMATTED)
    assert "+dependencies" in capsys.readouterr().out


def test_a_formatted_file_is_left_alone(project, capsys):
    main([str(project)])
    capsys.readouterr()
    assert main([str(project)]) == 0
    assert "no change for pyproject.toml" in capsys.readouterr().out


def test_check_writes_nothing(project, capsys):
    assert main(["--check", str(project)]) == 1
    assert project.read_text(encoding="utf-8").startswith(UNFORMATTED)
    assert "+dependencies" in capsys.readouterr().out


def test_no_print_diff_says_nothing_about_the_change(project, capsys):
    assert main(["--check", "--no-print-diff", str(project)]) == 1
    assert capsys.readouterr().out == ""


def test_stdout_writes_the_result_and_leaves_the_file(project, capsys):
    assert main(["--stdout", str(project)]) == 1
    assert project.read_text(encoding="utf-8").startswith(UNFORMATTED)
    assert capsys.readouterr().out.startswith(FORMATTED)


def test_a_directory_names_the_file_inside_it(project, capsys):
    assert main(["--stdout", str(project.parent)]) == 1
    assert capsys.readouterr().out.startswith(FORMATTED)


def test_stdin_is_read_and_written_back(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", _Reader(UNFORMATTED + NO_CLASSIFIERS))
    assert main(["-"]) == 1
    assert capsys.readouterr().out.startswith(FORMATTED)


def test_a_rejected_file_is_reported_and_left(project, capsys):
    project.write_text('[project]\nname = "x"\nversion = "not a version"\n', encoding="utf-8")
    assert main([str(project)]) == 1
    assert "not a valid PEP 440 version" in capsys.readouterr().err


def test_the_file_own_settings_are_read(project, capsys):
    project.write_text(UNFORMATTED + "[tool.pyproject-fmt]\ncolumn_width = 20\n", encoding="utf-8")
    main(["--stdout", str(project)])
    assert '\n  "a>=1",\n' in capsys.readouterr().out


def test_a_shared_config_beside_the_file_is_read(project, capsys):
    (project.parent / "pyproject-fmt.toml").write_text("keep_full_version = true\n", encoding="utf-8")
    project.write_text(UNFORMATTED + NO_CLASSIFIERS, encoding="utf-8")
    main(["--stdout", str(project)])
    assert '"a>=1.0.0"' in capsys.readouterr().out


def test_an_explicit_config_is_read(project, tmp_path, capsys):
    held = tmp_path / "held.toml"
    held.write_text("keep_full_version = true\n", encoding="utf-8")
    main(["--stdout", "--config", str(held), str(project)])
    assert '"a>=1.0.0"' in capsys.readouterr().out


def test_a_config_that_does_not_exist_is_refused(project):
    with pytest.raises(SystemExit):
        main(["--config", "nowhere.toml", str(project)])


def test_a_setting_the_formatter_does_not_know_is_refused(project, capsys):
    project.write_text(UNFORMATTED + "[tool.pyproject-fmt]\nnope = 1\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--stdout", str(project)])
    assert "unknown setting" in capsys.readouterr().err


def test_a_setting_written_as_the_wrong_thing_is_refused(project, capsys):
    project.write_text(UNFORMATTED + '[tool.pyproject-fmt]\ncolumn_width = "wide"\n', encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--stdout", str(project)])
    assert "is not written as int" in capsys.readouterr().err


def test_a_choice_the_setting_does_not_offer_is_refused(project, capsys):
    project.write_text(UNFORMATTED + '[tool.pyproject-fmt]\ntable_format = "wide"\n', encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--stdout", str(project)])
    assert "invalid choice" in capsys.readouterr().err


def test_a_path_that_names_nothing_is_refused():
    with pytest.raises(SystemExit):
        main(["nowhere.toml"])


def test_the_line_ending_the_file_used_is_kept(project):
    project.write_bytes((UNFORMATTED + NO_CLASSIFIERS).replace("\n", "\r\n").encode())
    main([str(project)])
    assert b"\r\n" in project.read_bytes()


@pytest.mark.parametrize(
    ("flag", "shows"),
    [
        (["--keep-full-version"], '"a>=1.0.0"'),
        (["--indent", "4"], "    "),
        (["--table-format", "long"], "[project]"),
    ],
)
def test_a_flag_reaches_the_formatter(project, capsys, flag, shows):
    project.write_text(UNFORMATTED + "[tool.pyproject-fmt]\ncolumn_width = 20\n", encoding="utf-8")
    main(["--stdout", *flag, str(project)])
    assert shows in capsys.readouterr().out


class _Reader:
    """Stands in for standard input."""

    def __init__(self, text: str) -> None:
        self.text = text

    def read(self) -> str:
        """Everything the caller wrote."""
        return self.text
