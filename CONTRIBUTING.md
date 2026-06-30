# Contributing to naja-scope

Thanks for your interest in naja-scope! Contributions of all kinds are
welcome — bug reports, feature requests, documentation, and code.

## Reporting bugs & requesting features

Please [open an issue](https://github.com/najaeda/naja-scope/issues). For bugs,
include:

- what you ran (the design, the tool call or agent prompt),
- what you expected and what actually happened,
- your OS, Python version, and `naja-scope` / `najaeda` versions
  (`naja-scope-mcp --version` and `pip show najaeda`).

## Development setup

naja-scope is a pure-Python package. Use Python 3.10+.

```sh
git clone https://github.com/najaeda/naja-scope.git
cd naja-scope
python -m venv .venv
.venv/bin/pip install -e .
```

This pulls `najaeda` and the MCP runtime from PyPI.

## Running the tests

```sh
.venv/bin/python -m pytest -q
```

Some heavier regression tests skip automatically unless their cached fixtures
are present, so a plain run is fast and self-contained.

## Submitting changes

1. Fork the repo and create a branch off `main`.
2. Make your change, with tests where it makes sense.
3. Ensure `pytest` passes.
4. Open a pull request describing the change and the motivation.

CI runs the test suite across supported Python versions on every pull request.

## Code style

Match the surrounding code. Keep tool docstrings tight — they are the schemas
agents pay tokens for on every session.

## Questions

For anything not covered here, reach us at
[contact@keplertech.io](mailto:contact@keplertech.io).
