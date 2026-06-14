# najaeda feedback from naja-scope (phase 1)

Findings while building the MCP layer, first against najaeda 0.5.2 (the
version installed when work started), retested against 0.7.0 (current PyPI,
now the project floor). Per project rules, missing capabilities become
najaeda feature requests — no private hooks. Each item has a repro against
`tests/fixtures/uart.sv` unless noted.

Notable 0.7.0 change: sequential lowering now produces word-level FF
primitives (`naja_dffrn__w8` — one instance per register, not per bit),
which shrinks driver/load/cone answers and is strictly better for the agent
use case.

## Feature requests

1. **Expose `sv_src_*` RTL infos through the Python bindings** (the DESIGN.md
   week-1 item). Today the only egress is
   `dump_verilog(dumpRTLInfosAsAttributes=True)`; naja-scope works around it
   by dumping annotated Verilog at index time and parsing the attributes back
   (`src/naja_scope/source_index.py`). A `get_rtl_info()` /
   `get_attributes()`-visible form on SNL objects removes the dump+parse.
   See [§ Design proposal](#design-proposal-rtlinfos-structuring--snlslang-coupling)
   for how to structure this so it is also cheap and serializable.
2. **`sv_symbol_path` RTL info** (slang hierarchical path) stamped at lowering
   time alongside `sv_src_*` — the persistent join key phase 2 needs to
   re-bind a live slang AST to a snapshot-loaded SNL (DESIGN.md prep hook 1).
   The path is *already computed* during lowering for naming
   (`SNLSVConstructor.cpp:15636`, `symbol.getHierarchicalPath()`); the ask is
   to intern and keep it. See [§ Design proposal](#design-proposal-rtlinfos-structuring--snlslang-coupling).
3. **Stable names for lowered objects at construction time** — primitive
   instances created by sequential/comb lowering are unnamed; the dumper
   invents `instance_N` names. naja-scope names them post-load
   (`src/naja_scope/naming.py`, derived from the driven net, e.g.
   `tx_o_dff`); doing this during lowering would make names canonical
   everywhere.

## Bugs found

1. **Parameter specializations merged** *(0.5.2 — FIXED in 0.7.0)*: in
   `uart.sv`, `counter #(.W(3))` and `counter #(.W(4))` both elaborated to a
   single `counter` model with a 4-bit `count` port. 0.7.0 correctly
   produces `counter` and `counter__elab1`.
2. **Process-killing exception on multi-output primitives** *(still in
   0.7.0)*:
   `Instance.is_buf()/is_const()/is_inv()` →
   `NLDB0::getPrimitiveTruthTable` throws an uncaught C++ `NLException` on
   `naja_fa` ("FA has two outputs") which terminates the interpreter
   (`libc++abi: terminating`). Any design containing an adder kills
   `najaeda.stats.compute_instance_stats`. naja-scope ships its own
   truth-table-free stats walker (`api.get_stats`). The exception should be
   translated to a Python exception, and `is_buf/is_const/is_inv` should
   return False for multi-output primitives.
3. **naja-if snapshots of SV-loaded designs do not reload** *(still in
   0.7.0)*: `dump_naja_if` + `reset` + `load_naja_if` fails with
   `cannot deserialize instance 0: model not found (reference dbID ...)` for
   designs lowered from SystemVerilog (works for the trivial counter-only
   design; fails as soon as comparisons/assigns appear, with or without
   `keep_assigns`). 15-line repro: load `bisect1.sv` (a counter plus
   `assign tick = (count == 8'hFF)`), dump, reset, load. Likely instances
   referencing models in the universe DB (NLDB0) that are not serialized.
   Tracked by `tests/test_zz_snapshot.py::test_snapshot_reload_roundtrip`
   (strict xfail). **Critical path:** per the
   [§ Design proposal scope decision](#scope-decision-2026-06-14-one-producer-one-re-entrant-path),
   naja-if is the only re-entrant path for RTLInfos, so this bug also blocks
   source-info persistence — not just fast reload.
4. **`Instance.get_design()` raises on top** *(still in 0.7.0)*:
   `IndexError: pop from empty list` when called on the top instance
   (netlist.py:1536) — guard `len(self.pathIDs) == 0`.
5. **Anonymous primitive *model*** *(0.5.2; not reproduced on this design in
   0.7.0)*: one lowered buffer primitive had an empty model name (showed up
   as `(unnamed)` in stats). Lowered primitive models should always be named.
6. **C++ logging goes to stdout** *(still in 0.7.0)*
   (`[naja] [warning] ...`), which corrupts
   stdio JSON-RPC transports. naja-scope reroutes fd 1 to stderr in
   `server.main()`. A way to direct naja logs to stderr (or a Python logging
   bridge) would help every embedder.

## Design proposal: RTLInfos structuring + SNL↔slang coupling

Forward-looking; grounded in the naja C++ checkout at `/Users/xtof/WORK/naja2`
(read 2026-06-13). This expands feature requests 1–2 from "expose it" into
"expose it in a shape that is cheap at MegaBoom scale and ready for the
phase-2 living AST." File:line references are into that checkout.

### Scope decision (2026-06-14): one producer, one re-entrant path

To keep this tractable for now, deliberately narrow the producer/persistence
model:

- **Warm slang elaboration is the only producer of `SNLRTLInfos`.** Source
  ranges (and the `symbolPathId` join key) are stamped during lowering, as
  today.
- **Verilog dump stays a one-way export.** `dumpRTLInfosAsAttributes` emits
  `(* sv_src_* *)` for human/tool consumption, but reloading that Verilog is
  **not** re-entrant: the Verilog frontend will keep dropping pragmas into the
  generic `SNLAttributes` bag (`SNLVRLConstructor.cpp:69,91`) and will *not*
  reconstruct `SNLRTLInfos`. No source-attribute recognizer, no gate-pragma
  producer — explicitly out of scope.
- **naja-if is the only re-entrant / round-trip path.** The single supported
  way RTLInfos (and symbolPathId) survives a save/reload is naja-if
  serialization.

**Consequence — this puts two items on the critical path that were
"nice-to-have" before:**

1. **RTLInfos must serialize to capnp** (Proposal A, Level 0 serialization
   half). It is now the *only* persistence mechanism, not an optimization.
2. **The naja-if SV-snapshot reload bug must be fixed** (Bugs §3 — currently
   `cannot deserialize instance 0: model not found`). With Verilog round-trip
   off the table, a broken naja-if reload means RTLInfos cannot persist *at
   all*. Bug §3 is therefore a blocker for the persistence story, not just a
   fast-reload convenience.

Until both land, naja-scope keeps its in-session `source_index.py` bridge and
treats snapshot reload as unavailable (its strict xfail stands).

### What exists today

Two parallel per-object metadata systems hang off `SNLDesignObject` /
`SNLDesign`, and source info is in the weaker one:

| | `SNLRTLInfos` (holds `sv_src_*`) | `SNLAttributes` |
|---|---|---|
| Storage | `std::map<NLName,std::string>` behind a raw owning `rtlInfos_` pointer (`SNLRTLInfos.h:27`, `SNLDesignObject.h:80`) | `NajaPrivateProperty` with typed `NUMBER`/`STRING` values (`SNLAttributes.h`) |
| Python | **not bound** | bound (`getAttributes`/`addAttribute`) |
| naja-if snapshot | **not serialized** | **also not serialized** — it is a `NajaPrivateProperty`, and capnp only dumps `getDumpableProperties()` → `NajaDumpableProperty*` (`SNLCapnPInterface.cpp:43,62`; `NajaObject.h:50`) |
| Clone | full `std::map` copy per uniquification (`SNLRTLInfos::cloneInfos`, called at `SNLSVConstructor.cpp:3221`) | `cloneAttributes` |

Per annotated object, `annotateSourceInfo` (`SNLSVConstructor.cpp:3245-3264`)
stores **five** map entries — `sv_src_file`, `sv_src_line`, `sv_src_column`,
`sv_src_end_line`, `sv_src_end_column`. So each object carries: 1 heap
`SNLRTLInfos` + 1 `std::map` + 5 RB-tree nodes + 5 `std::string` values.
Costs that matter at scale:

- **Integers stored as decimal text.** `line`/`column` go through
  `std::to_string` (`:3256-3263`) and naja-scope parses them straight back to
  `int`. Pure round-trip waste.
- **The filename is a full `std::string` on every object.** `NLName` interns
  the *key* `sv_src_file`, never the *value* — `"counter.sv"` is duplicated
  once per object in the file.
- **`cloneRTLInfos` deep-copies the map at every uniquification clone.** The
  perf report already counts `rtlInfoClonedEntries` and
  `cloneRTLInfosDuration` (`:3229-3232`), and DESIGN.md flags uniquification
  as exactly where naive maps break.
- **Neither bound nor serialized is the whole reason
  `src/naja_scope/source_index.py` exists** — the dump-Verilog-and-reparse
  bridge is a pure workaround for these two egress gaps.

### Proposal A — restructure RTLInfos (cheapest first)

A source range is a fixed-schema record, not open-ended metadata; it is being
shoehorned into a string map.

- **Level 0 — egress only (unblocks naja-scope now, no restructure).** Bind
  `getRTLInfos()` to PyNaja and serialize it to capnp. Alone this deletes
  `source_index.py` and fixes the phase-2 cold-start tier.
- **Level 1 — typed slot + interned file (recommended).**
  ```cpp
  struct SNLSourceLoc {            // 16 bytes, POD, trivially copyable
    uint32_t fileId;              // index into a per-DB file table
    uint32_t line, endLine;
    uint16_t column, endColumn;
  };
  class SNLRTLInfos {
    std::optional<SNLSourceLoc> sourceLoc_;   // the common case
    uint32_t symbolPathId_ {kInvalid};        // Proposal B, tier 1
    std::unique_ptr<Infos> extra_;            // nullptr unless rare k/v used
  };
  ```
  File names live in one `std::vector<std::string>` (or `NLName` table) per
  DB. `cloneInfos` becomes a 16-byte memcpy + int copy instead of 5 string
  allocations. The open-ended map stays for genuinely rare keys but is not
  allocated for the source-only common case. Best value/effort point.
- **Level 2 — columnar side table (only if MegaBoom profiling demands it).**
  Drop the per-object `rtlInfos_` pointer; hold `std::vector<SNLSourceLoc>`
  indexed by object id in the DB. Cache-friendly for the scans a query layer
  does, serializes as one blob, and is literally the in-engine version of the
  naja-scope sidecar. More invasive (object-id stability); hold unless the
  per-object allocation is shown to dominate.

### Proposal B — SNL↔slang coupling (two tiers, not one map)

The join is lossy both ways — uniquification maps one slang
`InstanceBodySymbol` to N SNL designs; bit-blasting maps one statement to many
primitives — so a single symbol-path map collides. Two tiers:

- **Tier 1 — persistent key, snapshot-survivable: `symbolPathId`.** Intern the
  slang hierarchical path (already computed at `SNLSVConstructor.cpp:15636`)
  into the `symbolPathId_` slot from Proposal A. Being a string slang can
  regenerate, a cold re-elaboration rebinds by walking slang symbols and
  matching ids — no live pointers needed. (DESIGN.md prep hook 1, made cheap
  by the typed struct.)
- **Tier 2 — exact live binding: `SNLDesignObject* ↔ const slang::ast::Symbol*`
  bimap.** Build it at the `cloneRTLInfos` site, where the 1→N fan-out happens
  and a path-only map would collide. Raw pointers are safe because the
  compilation is alive and immutable in-session. Prerequisite: move
  `compilation_` out of `SNLSVConstructorImpl` (a `unique_ptr` member at
  `SNLSVConstructor.cpp:28111`, currently dies with the constructor) into a
  session object that owns both the SNL DB and the compilation — the contained
  ownership refactor DESIGN.md anticipates.

**PyNaja exposure (the efficiency lever).** Rather than choosing between
DESIGN.md option 2 (curated `get_type`/`get_process` API) and option 3 (full
pyslang), expose the *bimap itself* at the PyNaja level:

```python
sym  = naja.ast_symbol_of(snl_object)      # raw pointer hop — no re-elab, no serialize
objs = naja.snl_objects_of(slang_symbol)   # inverse, 1→N
```

pyslang then rides on top for the actual intent queries (types, params,
processes, assertions), and `query_python` agents get the full slang surface
they already know. The win is that the link is a pointer lookup, not
re-elaboration (option 1's cost) nor a serialized copy.

**The one real decision this forces:** pyslang must be built from naja's exact
slang fork commit, or naja.so must expose a thin slang-symbol accessor
compiled in-tree. That ABI lockstep is the gate between "option 2, safe" and
"option 3, powerful" — worth deciding deliberately rather than drifting into.

## Frontend coverage notes (beta, expected but user-facing)

- Sequential lowering rejects 3+-branch `if/else if` chains in `always_ff`
  and `case` inside `always_ff` ("fallback currently supports only multi-LHS
  reset branches"). Next-state logic must live in `always_comb`. This is
  DESIGN.md risk #1; error messages are good (file:line), naja-scope
  surfaces them verbatim.
- `===` in case statements is lowered as 2-state comparison with a warning.
