# Changelog

All notable changes to naja-scope are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-06-29

### Added
- `naja-scope-mcp --help` and `--version` flags, so running the server
  interactively prints usage instead of emitting JSON-RPC parse errors.
- `examples/` — a self-contained UART design and a scripted tour
  (`walkthrough.py`), with a regression test that pins the documented answers.

### Changed
- Rewrote the PyPI landing page to be user-focused, with install/usage,
  a CVA6 benchmark, and contact details.

## [0.1.0] - 2026-06-29

### Added
- Initial public release.
- MCP server (`naja-scope-mcp`) exposing tools for AI agents to navigate
  elaborated SystemVerilog designs: hierarchy, connectivity (drivers/loads),
  logic cones, source back-links, module cards, and design-intent recovery
  (enum/struct/parameter facts erased during elaboration).
- Built on [najaeda](https://github.com/najaeda/naja) (`najaeda>=0.7.8`).

[0.1.1]: https://github.com/najaeda/naja-scope/releases/tag/v0.1.1
[0.1.0]: https://github.com/najaeda/naja-scope/releases/tag/v0.1.0
