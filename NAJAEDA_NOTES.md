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
   week-1 item). **RESOLVED for source ranges in najaeda 0.7.2:**
   `SNLDesignObject.getSourceLoc()` / `hasSourceLoc()` read the range directly
   (naja #389/#390), so the old dump-Verilog-and-reparse workaround is gone, and
   `src/naja_scope/source_index.py` was since **deleted entirely** — ranges are
   read on-demand via `getSourceLoc` (see `docs/identity-and-addressing.md`). A
   broader `get_rtl_info()` / `get_attributes()`-visible egress (for the *other*
   RTL infos, e.g. `sv_symbol_path`) + capnp serialization is still tracked in
   [§ Design proposal](#design-proposal-rtlinfos-structuring--snlslang-coupling)
   for the phase-2 cold-start tier.
2. **`sv_symbol_path` RTL info** (slang hierarchical path) stamped at lowering
   time alongside `sv_src_*` — the persistent join key phase 2 needs to
   re-bind a live slang AST to a snapshot-loaded SNL (DESIGN.md prep hook 1).
   The path is *already computed* during lowering for naming
   (`SNLSVConstructor.cpp:16313`, `symbol.getHierarchicalPath()`); the ask is
   to intern and keep it. **Filed as a standalone FR:**
   `docs/naja-feature-request-sv-symbol-path.md` (the cold-start tier-1 key that
   the tier-2 coupling FR #9 degrades to). See also
   [§ Design proposal](#design-proposal-rtlinfos-structuring--snlslang-coupling).
3. **Stable names for lowered objects at construction time** — *SUPERSEDED, do
   not implement.* Originally: lowered primitives are unnamed, so naja-scope
   named them post-load (`naming.py`, driven-net-derived, e.g. `tx_o_dff`). The
   chosen direction instead addresses an anonymous instance by its stable
   per-design **id** (`getID()` / `getInstanceByID()`, the `#<id>` path segment,
   snapshot-stable) and derives a friendly label lazily — no eager naming pass,
   no naja-side construction naming. `naming.py` is deleted; see
   `docs/identity-and-addressing.md` and
   `docs/naja-feature-request-NLID-python-class.md` (the najaeda 0.7.7 `NLID`
   class + `getObject` that back it).
4. **`SNLLogicalCone` must cross SV-lowered logic gates** *(0.7.5 — shipped but
   blocked; the cone tool's intended C++ backend, requested in
   `docs/naja-feature-request-SNLLogicalCone.md`)*. `naja.SNLLogicalCone`
   (`(occurrence, FanIn|FanOut)`) crosses a leaf cell only when
   `SNLDesign.hasModeling()` is true. SV lowering gives combinational **gate**
   primitives (`and_2`, `or_2`, `not_1`, `and_3/5/8`, …) a `getTruthTable()` but
   **no combinatorial-arc modeling** (`hasModeling()==False`); only `assign` and
   `naja_mux2__w*` carry modeling. So the cone treats every and/or/not gate as
   an opaque `blackbox` and stops there. Out-of-the-box repro (cv32a6_imac_sv32,
   snapshot `eval/.cache/cva6-small`): fan-in of
   `cva6.ex_stage_i.i_mult.i_div.state_d` = 83 nodes/bit, 2 flops, all inside
   ex_stage — it does **not** reach the verified cross-hier frontier
   (`csr_regfile_i.priv_lvl_q`, `issue_stage_i.i_scoreboard`), which the
   hand-rolled equipotential `cone.py` reaches (491 nodes, 16-flop frontier, 10
   outside ex_stage). This **fails the cone FR's own acceptance criteria 5 and
   6**. Fix (either): SV lowering sets combinatorial arcs on gate primitives the
   way it already does for assign/mux (it already sets their truth tables); or
   `SNLLogicalCone` derives traversal from `getTruthTable()` when `hasModeling()`
   is absent. Verified 2026-06-22 against najaeda 0.7.5.
   **RESOLVED in naja3 / "future 0.7.6"** (checkout `/Users/xtof/WORK/naja2`'s
   successor `/Users/xtof/WORK/naja3`, HEAD `4e557f5d "Add Combinatorial
   Dependencies to NLDB0 and, or, xor, ... gates"` on top of `90b4128a adding
   logical cone (#393)`). With it the gate primitives carry modeling, the cone
   has zero gate black boxes, and the `state_d` fan-in cone reaches the
   cross-hier frontier (`csr_regfile_i.priv_lvl_q`,
   `issue_stage_i.i_scoreboard.commit_pointer_q`/`mem_q`). `cone.py` was rewritten
   onto `SNLLogicalCone` (no more equipotential BFS). NOTE the new cone's frontier
   is much larger than the old equipotential one (state_d: ~196 flops / 15401
   nodes vs 16 / 491) — see §6, still being reconciled. naja3's `.so` is built for
   Python 3.14 (segfaults under the 3.11 venv); naja-scope dev runs in `.venv314`.
6. **`SNLOccurrence` does not expose `getInstance()`** *(RESOLVED in 0.7.6;
   ergonomics)*. A `SNLLogicalCone` node tuple is `(id, occurrence, kind,
   next_ids, prev_ids)` (`PySNLLogicalCone.cpp:140`). For Internal/Flop/Blackbox
   nodes the `occurrence`'s object is an `SNLInstance` (`getPath()` is only the
   PARENT path), but Python `SNLOccurrence` binds just `getNetComponent()` /
   `getInstTerm()` / `getPath()` (`PySNLOccurrence.cpp:56-58`) — both casters
   return `None` for an instance, and there is no `getInstance()` or bound
   `getObject()`. The C++ `SNLOccurrence` holds the instance in `object_` and has
   the caster pattern (`getInstTerm()` = `dynamic_cast<SNLInstTerm*>(getObject())`,
   `SNLOccurrence.cpp:90`) but no `getInstance()`. So the only Python handle on
   the leaf is its name inside `repr(occurrence)` (= `getString('/')`,
   `SNLOccurrence.cpp:114`). `cone.py` works around it by parsing the repr
   (`snl.occurrence_tail_name`/`occurrence_leaf`) — fragile (assumes names have no
   `/`). **Fix:** add `SNLInstance* SNLOccurrence::getInstance() const` (a
   `dynamic_cast`, mirroring `getInstTerm`) and bind it
   (`GetObjectMethod(SNLOccurrence, SNLInstance, getInstance)`, exactly as
   `PySNLInstTerm.cpp:26` does for inst-terms). Then `occurrence_leaf` drops to
   `occ.getInstance()` + `occ.getPath().getInstanceIDs()`, no repr parse. Full
   hand-to-an-agent spec: `docs/naja-feature-request-occurrence-getInstance.md`.
   **RESOLVED in najaeda 0.7.6:** both `SNLOccurrence.getInstance()`
   (`GetObjectMethod`) and `SNLOccurrence.isInstanceOccurrence()`
   (`GetBoolAttribute`) are now bound (`PySNLOccurrence.cpp:59,61`). `cone.py` /
   `snl.occurrence_leaf` use `getInstance()`; the `repr()` parse
   (`occurrence_tail_name`, `_OCC_REPR_RE`, `import re`) is deleted.
7. **`SNLLogicalCone` frontier far exceeds the equipotential cone — reconcile**
   *(naja3 — INVESTIGATED 2026-06-22; NOT a defect, no FR)*. state_d fan-in:
   native cone 196 flops / ~7700 nodes/bit (2 bits) vs the old hand-rolled
   equipotential `cone.py` 16 / 491 — ~12x larger, the OPPOSITE of the cone FR's
   acceptance criterion 6 ("C++ leaf set a strict subset of the Python BFS").
   The native set pulls in ~100 `hpdcache_rtab_i.req_q_dff_*` and SRAM
   `rdata_dff` cells.

   **Verdict: 196 is the TRUE combinational fan-in; the old equipotential walk
   under-traced.** The arc model is precise — NOT over-broad. Decisive evidence
   (`naja.SNLDesign.getCombinatorialInputs/Outputs` on the lowered leaf cells,
   loaded from `eval/.cache/cva6-small/snapshot`):
   - `naja_mem` (the SRAM array leaf, `isSequential()==True`): `RDATA[i]`'s
     combinatorial-input set is **RADDR only** (just the log2(depth) address
     bits); `WDATA`/`WE`/`WADDR`/`CLK` each return an **empty** combinatorial-
     output set. Clean async-read RAM arc (RADDR→RDATA combinational; writes are
     sequential, no arc). No all-inputs→all-outputs coupling. The "over-connects
     memory cells" hypothesis is **false**.
   - `naja_mux2.Y` → {A,B,S} (3, correct); `naja_dff` D/Q → no combinatorial arc
     (correct sequential barrier). Lowered and/or/xnor are single-output, arcs OK.
   - Why the dcache flops are genuinely in-cone: the divider's `state_d` has
     `flush_i` as a real combinational input (canonical serdiv `if (flush_i)
     state_d = IDLE`). `flush_ex` is a global control reduction (controller →
     commit → fence/dcache handshake) that legitimately fans back through
     precise single-output arcs into csr, commit, controller, and the dcache
     (rtab `req_q`, wbuf, mshr, SRAM `rdata_dff`). A concrete root→leaf path was
     walked gate-by-gate (mux2/and/or/xnor/assign only) confirming this. The
     divider-local flops the old walk found (`state_q`, `op_b_zero_q`,
     `op_b_neg_one_q`, `div_res_zero_q`, `cnt_q`, `mult_valid_q`) are a subset of
     the 196. The old equipotential cone simply never crossed the hierarchical
     flush/control fabric (it stopped at the local module), so 16 ⊂ 196.

   **Implication for golden node counts:** trust 196 — it is correct. The real
   issue is *product/UX*, not modeling: a tiny FSM's next-state cone is dominated
   by the global flush network, which is technically-true-but-unhelpful for an
   agent asking "what does the divider depend on." Consider a future affordance
   (annotate/sever the flush-class control bridge, or report it separately) —
   but that is a naja-scope summarisation choice, NOT a naja arc-precision FR.

8. **`getNonAssignInstances()` / `getAssignInstances()` on SNL instance
   containers** *(SHIPPED in najaeda 0.7.6; partition of `getInstances()` by
   `model.isAssign()`)*. Closes eval finding #4 (top-level fan-out): the lowered
   `cva6` top has 4,866 direct children = 4,842 `assign` glue + 24 real (10
   submodules + 14 leaves), and `get_hierarchy` could only window the raw list.
   `snl.non_assign_child_nodes` calls these accessors directly.
   **Verified on PyPI 0.7.6 (2026-06-23): both bound on `SNLDesign`.** The
   `pyproject.toml` floor is `najaeda>=0.7.6` and the earlier `hasattr` fallback
   has been removed.

9. **Keep the slang `Compilation` alive + expose the SNL↔slang link** (phase-2
   P2.2; NAJAEDA_NOTES Proposal B tier 2). `compilation_` is a `unique_ptr`
   member of the SV constructor (moved in at `SNLSVConstructor.cpp:1166,1193,
   1259,2010`, used at `:1050`) and **dies with the constructor** — taking every
   enum/typedef/param/process/assertion intent with it. The ask: a contained
   ownership refactor moving the Compilation to a session-lifetime owner, plus a
   `SNLDesignObject* ↔ const slang::ast::Symbol*` bimap stamped at the
   uniquification clone site (`cloneRTLInfos` `:3512`/`:3534`, beside
   `annotateSourceInfo` `:2755`), exposed as PyNaja `ast_symbol_of` /
   `snl_objects_of` so pyslang rides on top as the query engine. This is the only
   sound link across uniquification (1→N) and bit-blasting (anonymous
   primitives), where the route-1 prototype's name/range matching collides.
   **Now justified, not speculative:** the naja-scope route-1 prototype passed its
   eval gate on cva6-small (scope+intent ≤ grep turns; see
   `docs/phase2-plan.md` §4). **Filed:**
   `docs/naja-feature-request-slang-coupling.md`. Depends on FR #2
   (`sv_symbol_path`) for the cold-start tier.

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
3. **naja-if snapshots of SV-loaded designs do not reload** *(0.5.2 through
   0.7.3 — FIXED in 0.7.4)*: `dump_naja_if` + `reset` + `load_naja_if` failed with
   `cannot deserialize instance 0: model not found (reference dbID ...)` for
   designs lowered from SystemVerilog (worked for the trivial counter-only
   design; failed as soon as comparisons/assigns appeared, with or without
   `keep_assigns`). The 15-line repro — load `bisect1.sv` (a counter plus
   `assign tick = (count == 8'hFF)`), dump, reset, load — now round-trips on
   0.7.4. Tracked by `tests/test_zz_snapshot.py::test_snapshot_reload_roundtrip`
   (now a normal passing test; the strict xfail marker was removed). **Critical
   path, now unblocked:** per the
   [§ Design proposal scope decision](#scope-decision-2026-06-14-one-producer-one-re-entrant-path),
   naja-if is the only re-entrant path for RTLInfos, so this fix also unblocks
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
2. **The naja-if SV-snapshot reload bug must be fixed** (Bugs §3 —
   `cannot deserialize instance 0: model not found`, **FIXED in 0.7.4**). With
   Verilog round-trip off the table, a broken naja-if reload meant RTLInfos
   could not persist *at all*. Bug §3 was therefore a blocker for the
   persistence story, not just a fast-reload convenience.

Item 2 landed in najaeda 0.7.4: SV-snapshot reload now round-trips, so naja-if
serialization is a real RTLInfos persistence path — and `getSourceLoc()` works
post-reload, so source ranges survive a snapshot with **no sidecar**. (naja-
scope's old `source_index.py` sidecar has since been deleted; ranges are read
on-demand.) The snapshot round-trip is a normal passing test
(`tests/test_zz_snapshot.py`).

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
- *(Historical)* the dump-Verilog-and-reparse bridge that
  `src/naja_scope/source_index.py` once was is gone — `getSourceLoc()` (0.7.2)
  replaced the reparse, and the prebuilt index itself was deleted (ranges read
  on-demand). The RTLInfos egress/serialization gaps below still matter for the
  richer `get_rtl_info()` phase-2 story, not for source ranges.

### Proposal A — restructure RTLInfos (cheapest first)

A source range is a fixed-schema record, not open-ended metadata; it is being
shoehorned into a string map.

- **Level 0 — egress only (no restructure).** Bind `getRTLInfos()` to PyNaja and
  serialize it to capnp. (`source_index.py` is already gone — source ranges come
  from `getSourceLoc`; this Level-0 egress is now about the *other* RTL infos,
  e.g. `sv_symbol_path`, for the phase-2 cold-start tier.)
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
