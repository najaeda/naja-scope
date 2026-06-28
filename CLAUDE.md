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
- Dependency: requires `najaeda>=0.7.8` (on PyPI since 2026-06-28; `.venv`,
  Python 3.11). Feature history (all present in the 0.7.8 floor): 0.7.2 shipped
  the source-access API (`getSourceLoc`, naja #389/#390); 0.7.4 fixed the naja-if
  SV-snapshot reload; 0.7.5 added `naja.SNLLogicalCone`; 0.7.6 added
  combinatorial modeling on the lowered gates (so the cone reaches the
  cross-hierarchy flop frontier — `cone.py` is built ENTIRELY on
  `SNLLogicalCone`) and partitioned `getInstances()` into
  `getNonAssignInstances()`/`getAssignInstances()`; 0.7.7 adds the Python `NLID`
  value class + `NLUniverse.getObject(NLID)` — the identity layer naja-scope
  addresses objects with (see docs/identity-and-addressing.md): anonymous
  instances by `#<id>` (`getID`/`getInstanceByID`, snapshot-stable) with friendly
  labels derived lazily, so there is NO eager naming/source-index pass
  (`ensure_names`/`SourceIndex.build` are gone); **0.7.8 adds the in-engine
  SNL↔slang link (`keep_ast_link`) + the curated `intent_*` API** the phase-2
  intent layer rides on (below). The full suite passes on the PyPI 0.7.8 wheel
  (`./.venv/bin/python -m pytest -q`, 60/60). A local naja build is still usable
  for naja-side dev (`.venv314`, Python 3.14, +
  `PYTHONPATH=/Users/xtof/WORK/naja3/build/test/najaeda`; that build is compiled
  for Homebrew Python 3.14 and segfaults under a 3.11 interpreter), but is no
  longer required — the PyPI wheel carries the intent API. Pin is
  `najaeda>=0.7.8` in `pyproject.toml`. See DESIGN.md fact 2 /
  Week 0, docs/identity-and-addressing.md, and NAJAEDA_NOTES.md.
- Phase 1 (structural spine + source ranges) is the core. The phase-2 eval gate
  has PASSED and been re-confirmed on the productized layer (scope+intent ≤ grep
  turns on cva6-small; docs/phase2-plan.md §4, GATE RE-CONFIRMATION 2026-06-28),
  so the **living-intent layer is now productized, not a prototype**: `get_intent`
  (`intent.py`, behind the `session.py` provider seam; **no extra Python dep** —
  not pyslang) is a thin client over naja's **in-engine `SNLDesignObject↔slang`
  link**
  (`keep_ast_link`) — it calls `naja.intent_*`, which walk the live slang AST in
  C++ and return plain dicts. There is **NO pyslang here and no second
  elaboration** (the earlier route-1 pyslang re-elaboration prototype is gone);
  naja owns the one AST. Keep it source-range/name-keyed and graceful when
  absent. Warm-only (the slang `Compilation` never serializes): a cold snapshot
  load degrades to "intent layer not loaded" and re-binds by re-elaborating from
  the snapshot-persisted `load_spec` (`load_intent` / `intent=true` /
  `NAJA_SCOPE_INTENT`; implemented + tested — `tests/test_zz_snapshot.py`). The
  relink-*without*-re-elaboration sub-tier (needs the `sv_symbol_path` naja FR) is
  still deferred. The C++ coupling itself lives in naja (FRs in
  docs/naja-feature-request-slang-coupling.md) — no naja C++ build dependency in
  this repo — and ships in the naja **0.7.8** wheel on PyPI (the declared
  `najaeda>=0.7.8` floor), so intent is functional on a plain `pip install`.
- Every tool response must be token-bounded: paginate lists, truncate cones
  with explicit markers, return counts and frontiers instead of dumps.
- Object references are hierarchical path strings; responses include source
  ranges (`file:start-end`) whenever known.

## Scope

RTL/design questions on synthesizable SystemVerilog. Not a DV/testbench tool
(see DESIGN.md §2 for what is lost in lowering and why).
