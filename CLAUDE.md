# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A `pyproject.toml` formatter written in pure Python: a reimplementation of
[pyproject-fmt](https://github.com/tox-dev/toml-fmt), which is Rust behind a PyO3 extension. The
formatting rules are the same ones; the output is checked against the reference over a corpus of
1,572 cases (`tests/data/corpus`).

The reference checkout is expected at `../toml-fmt`. It is the source of truth for every rule, and
the two scripts under `tools/` read it. Nothing at runtime depends on it.

The public surface is `format_toml(content, Settings(...))`, which raises `FormatError`, and the
`pyproject-fmt` console script.

`TODO.md` tracks the one-time repository setup that still has to be done by hand.

## Commands

Dependencies are managed with [uv](https://docs.astral.sh/uv/) and every task is
defined in `mise.toml`, which is the canonical list.

```bash
uv sync --all-groups                   # install runtime + dev + docs groups
mise run pytest                        # run the test suite
uv run pytest tests/test_corpus.py -k ruff  # one module's corpus cases
mise run ruff                          # format + autofix (uv format)
mise run ty                            # type check (uvx ty check)
mise run pymarkdown                    # markdown lint
mise run pyproject-fmt                 # format this repository's own pyproject.toml
mise run pre-commit                    # ruff + ty + pymarkdown + pyproject-fmt
mise run ci                            # pre-commit + pytest-cov -- what CI runs
mise run corpus                        # regenerate the golden corpus from the reference
mise run compat                        # report where this and the reference differ
mise run build                         # build sdist + wheel
mise run docs                          # pdoc API docs into ./docs
mise run pinup                         # update the pinned action/image digests
mise run build-binary                  # PyInstaller standalone binary into ./dist
```

The reference ships a `pyproject-fmt` console script of the same name as this project's, so it is
never installed into `.venv`: `mise run compat` and `mise run corpus` put it in a throwaway
environment instead. If `uv run pyproject-fmt` ever reports `Failed to spawn`, the script was
clobbered and `uv sync --all-groups --reinstall-package pyproject-fmt-py` puts it back.

The venv is tied to the absolute repo path (`uv sync` bakes it into script shebangs). If the
repo directory gets renamed or moved, delete `.venv/` and `uv sync` again rather than debugging
"No such file or directory" / `ModuleNotFoundError` -- it is a stale interpreter path, not a
code bug.

Lint config lives in `pyproject.toml`: Ruff with `lint.select = ["ALL"]` and `line-length = 120`.
Prefer a targeted `lint.per-file-ignores` entry with a comment over a scattered `# noqa`.

## Architecture

Parsing is `tomlkit`'s; everything else is this package's. A source is read into a flat,
line-oriented document, the rules rewrite that document, and an emitter writes it back out. No rule
ever touches whitespace, and the layout is decided in one place.

```text
source --tomlkit--> document.Document --rules/*--> document.Document --render--> text
```

### The engine

- **`document.py`** -- the model and the reader. A document is the entries written before the first
  header plus the sections each header opens; an entry's key is the whole path it writes, so
  `a.b = 1` is one entry of two segments rather than a table holding another. Comments and blank
  lines attach to what sits below them, so reordering carries them along.
- **`render.py`** -- the emitter: what goes around `=`, inside brackets, where an array breaks, and
  how the comments inside one line up.
- **`spacing.py`** / **`wrapping.py`** / **`strings.py`** / **`width.py`** -- the gaps between
  tables, breaking a long string across lines, choosing a quote, measuring columns.
- **`ordering.py`** / **`sections.py`** -- ranking tables and keys, and finding a table by name
  however the file spelled its path: `[tool.ruff] lint.select`, `[tool.ruff.lint] select` and
  `[tool.ruff] lint = { ... }` all name the same key, and a rule reads all three.
- **`nesting.py`** -- folding `[a.b]` into `[a]` as dotted keys and writing them back out.
- **`arrays.py`** / **`sorting.py`** -- reordering array members, and the natural, accent-aware
  order almost every list in a formatted file reads in.
- **`disabled.py`** -- a comment whose body is one key-value is a field the author turned off; it is
  uncommented, formatted with its table, and commented back. Any pass that would split, drop or
  merge such an entry has to leave it alone, which `is_enabled_here` is what says.
- **`pep440.py`** / **`pep508.py`** -- versions and dependencies, read and written this package's
  own way rather than `packaging`'s, since the spelling is part of what the rules ask for.

### The rules

`rules/__init__.py` is the registry: which tables the formatter recognizes and what each asks for.
Most tool tables are a key order plus a list of arrays that hold a set, and those live as data in
`rules/_data.py`, generated by `tools/extract_rules.py` from the reference -- edit the script and
run it again rather than that file. The tables with rules of their own are modules beside it:
`build_system`, `project` (with `classifiers`), `dependency_groups`, `poetry`, `hatch`,
`setuptools`, `tox`, and `tools` (towncrier, pyright, pdm, cibuildwheel, mypy).

`formatter.py` runs them in the order they read each other's work; changing that order changes the
output.

### The command line

`cli.py` builds one option set per input: the flags, then a `pyproject-fmt.toml` found beside the
file or above it, then the `[tool.pyproject-fmt]` table the file itself holds. What is written
closer to the file wins. `settings_file.py` reads both.

## Testing conventions

Tests live in `tests/` and mirror the module split. The bulk of them is the golden corpus:

- `tests/data/corpus/<module>/<case>.txt` holds one source and what each profile in
  `tests/profiles.py` should make of it. `tests/corpus.py` reads and writes that format.
- `tests/test_corpus.py` runs every case, and also checks that the result parses and that
  formatting it again changes nothing.
- `tests/data/known_failures.txt` lists the cases that do not pass yet, marked `xfail(strict=True)`
  so one that starts passing fails until its line goes. `pytest --update-known-failures` rewrites
  it. It is currently empty.
- `tools/extract_corpus.py` regenerates the corpus from the reference's Rust test sources. The
  expectations in it are this repository's own: where a rule is deliberately different, edit the
  case file and say why, rather than changing the tool.

`tests/**` has its own `lint.per-file-ignores` block, so assertions and missing annotations are
fine there.

## Versioning and releases

Versions come from git tags via `uv-dynamic-versioning`; nothing in the repo hard-codes one.
Pushing a `v*.*.*` tag runs `build-binaries.yml`, which builds one binary per OS/arch on native
runners (PyInstaller cannot cross-compile), attaches them to a **draft** release and publishes it
afterwards -- immutable releases lock the assets of an already published release. `release.yml`
then reacts to `release: [published]` and does the PyPI and GHCR publish.
