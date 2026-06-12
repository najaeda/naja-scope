# naja-scope

Agent-facing query layer over najaeda: an MCP server whose tools let AI agents
navigate elaborated SystemVerilog designs (hierarchy, connectivity, drivers,
cones, source back-links) without loading source code into context.

Read DESIGN.md before any non-trivial work — it is the source of truth for
architecture, scope, phasing, and the tool API.

## Rules

- Thin layer over the public `najaeda` pip API, plus the raw `naja` bindings it
  ships. If a needed capability is missing, it becomes a najaeda feature
  request (local naja checkout for reference: /Users/xtof/WORK/naja2) — no
  private hooks, no naja C++ build dependency in this repo.
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
