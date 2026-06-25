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
- Dependency: requires `najaeda>=0.7.7`. Feature history (all present in the
  0.7.7 floor): 0.7.2 shipped the source-access API (`getSourceLoc`, naja
  #389/#390); 0.7.4 fixed the naja-if SV-snapshot reload; 0.7.5 added
  `naja.SNLLogicalCone`; 0.7.6 added combinatorial modeling on the lowered gates
  (so the cone reaches the cross-hierarchy flop frontier — `cone.py` is built
  ENTIRELY on `SNLLogicalCone`) and partitioned `getInstances()` into
  `getNonAssignInstances()`/`getAssignInstances()`; **0.7.7 adds the Python
  `NLID` value class + `NLUniverse.getObject(NLID)`** — the identity layer
  naja-scope addresses objects with (see docs/identity-and-addressing.md):
  anonymous instances by `#<id>` (`getID`/`getInstanceByID`, snapshot-stable)
  with friendly labels derived lazily, so there is NO eager naming/source-index
  pass (`ensure_names`/`SourceIndex.build` are gone). **0.7.7 is not on PyPI yet
  (pushed later)**, so dev runs against the local naja build via `.venv314`
  (Python 3.14) + `PYTHONPATH=/Users/xtof/WORK/naja3/build/test/najaeda`:
  `PYTHONPATH=/Users/xtof/WORK/naja3/build/test/najaeda ./.venv314/bin/python -m
  pytest -q` (the build is compiled for Homebrew Python 3.14 and segfaults under
  a 3.11 interpreter). The src refactor still runs on PyPI 0.7.6 (it only needs
  `getID`/`getInstanceByID`), but the declared floor and identity model are
  0.7.7. Pin is `najaeda>=0.7.7` in `pyproject.toml`. See DESIGN.md fact 2 /
  Week 0, docs/identity-and-addressing.md, and NAJAEDA_NOTES.md.
- Phase 1 (structural spine + source ranges) is the core. The phase-2 eval gate
  has PASSED (scope+intent ≤ grep turns on cva6-small; docs/phase2-plan.md §4),
  so the **route-1 living-intent prototype is now in**: `get_intent` over a
  warm-only, opt-in `pyslang` re-elaboration (`intent.py`, behind the `session.py`
  provider seam; optional `[intent]` dep). It is a PROTOTYPE — keep it
  source-range/name-keyed and graceful when absent. The exact in-engine
  `SNLDesignObject↔slang` link (P2.2, naja C++; FRs in
  docs/naja-feature-request-slang-coupling.md) stays out of scope here — no naja
  C++ build dependency in this repo.
- Every tool response must be token-bounded: paginate lists, truncate cones
  with explicit markers, return counts and frontiers instead of dumps.
- Object references are hierarchical path strings; responses include source
  ranges (`file:start-end`) whenever known.

## Scope

RTL/design questions on synthesizable SystemVerilog. Not a DV/testbench tool
(see DESIGN.md §2 for what is lost in lowering and why).
