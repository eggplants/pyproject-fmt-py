# pyproject-fmt-py

[![PyPI](
  <https://img.shields.io/pypi/v/pyproject-fmt-py?color=blue>
  )](
  <https://pypi.org/project/pyproject-fmt-py/>
) [![CI](
  <https://github.com/eggplants/pyproject-fmt-py/actions/workflows/ci.yml/badge.svg>
  )](
  <https://github.com/eggplants/pyproject-fmt-py/actions/workflows/ci.yml>
)

[![ghcr size](
  <https://ghcr-badge.egpl.dev/eggplants/pyproject-fmt-py/size>
)](
  <https://github.com/eggplants/pyproject-fmt-py/pkgs/container/pyproject-fmt-py>
)

A `pyproject.toml` formatter written in pure Python, reimplementation of [pyproject-fmt](https://github.com/tox-dev/toml-fmt).

## Installation

```bash
# mise via github release
mise use -g github:eggplants/pyproject-fmt-py

# mise via pipx
mise use -g pipx:pyproject-fmt-py

# pipx
pipx install pyproject-fmt-py

# pip
pip install pyproject-fmt-py
```

### Docker

```bash
docker pull ghcr.io/eggplants/pyproject-fmt-py

docker run --rm -v "$PWD:/w" -w /w ghcr.io/eggplants/pyproject-fmt-py pyproject.toml
```

## CLI

```shellsession
$ pyproject-fmt pyproject.toml
--- pyproject.toml
+++ pyproject.toml
@@ -1,3 +1,3 @@
 [project]
-name="My_Package"
-dependencies=["b","a >= 1.0.0"]
+name = "my-package"
+dependencies = [ "a>=1", "b" ]

$ pyproject-fmt --check pyproject.toml   # fail without writing
$ pyproject-fmt --stdout pyproject.toml  # write the result to stdout
$ cat pyproject.toml | pyproject-fmt -   # read from stdin
```

### Settings

```toml
[tool.pyproject-fmt]
column_width = 120
indent = 2
# "long" writes each sub-table under a header of its own
table_format = "short"
# true keeps a redundant `.0` in a dependency version
keep_full_version = false
max_supported_python = "3.15"
```

## Library

```python
from pyproject_fmt_py import Settings, format_toml

print(format_toml('[project]\nname="My_Package"\n', Settings()))
```

`format_toml` raises `FormatError` when the source is not a document, or
says something the rules reject, such as a `project.version` does not read.

## License

[MIT License](
  <https://github.com/eggplants/pyproject-fmt-py/blob/master/LICENSE.txt>
)
