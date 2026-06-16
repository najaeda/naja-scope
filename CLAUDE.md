# naja-scope

Agent-facing query layer over najaeda: an MCP server whose tools let AI agents
navigate elaborated SystemVerilog designs (hierarchy, connectivity, drivers,
cones, source back-links) without loading source code into context.

Read DESIGN.md before any non-trivial work — it is the source of truth for
architecture, scope, phasing, and the tool API.

## Rules

- Built on the raw `naja` bindings (`from najaeda import naja` — the PySNL
  interface to the SNL C++ API), centralised in `snl.py` and `loader.py`. The
  high-level `najaeda.netlist` wrappers are NOT used anywhere — querying,
  navigation, connectivity, loading, and snapshots all go through raw SNL.
  (`najaeda.primitives` is still used by `loader.load_primitives` for the
  bundled xilinx/yosys libraries; that is library content, not the netlist
  layer.) If a capability is missing from raw naja, it becomes a naja feature
  request (local checkout: /Users/xtof/WORK/naja2) — no private hooks, no naja
  C++ build dependency in this repo.
- Dependency: requires `najaeda>=0.7.2` (the source-access API — source ranges
  / `getSourceLoc`, naja #389/#390 — shipped to PyPI in 0.7.2). Pin it in
  `pyproject.toml`. Earlier 0.5.x lacks the API. See DESIGN.md fact 2 / Week 0.
- Phase 1 only (DESIGN.md §9): structural spine + source ranges. The living
  slang AST layer (DESIGN.md "Phase 2") stays out of scope until the eval gate
  passes.
- Every tool response must be token-bounded: paginate lists, truncate cones
  with explicit markers, return counts and frontiers instead of dumps.
- Object references are hierarchical path strings; responses include source
  ranges (`file:start-end`) whenever known.

## Scope

RTL/design questions on synthesizable SystemVerilog. Not a DV/testbench tool
(see DESIGN.md §2 for what is lost in lowering and why).
