# Phase 2 plan — the living intent layer

*Decision document. The Phase-1 eval gate (DESIGN.md §9 Week 3) passed — verdict
**Go** (scope 13/13 vs grep 9/13 on cv64a6_imafdc_sv39; see `eval/RESULTS.md`).
This doc turns the eval's **intent-question baseline** into a Phase-2 go/no-go and
a scoped, gated first step. It does not restate the Phase-2 architecture — that
lives in DESIGN.md "Phase 2" and "Phase-1 prep hooks for phase 2"; here we commit
to a sequence and a measurable gate.*

## 1. The decision input (what the eval actually showed)

Phase 1 wins decisively on the **post-elaboration** class (flattened counts,
post-lowering drivers, uniquified variants, cross-hierarchy cones) — answers that
are *not in the source text*, where grep is wrong or hallucinates. That is settled.

The **intent-class** questions are the opposite story. They were answered the
phase-1 way (source-range + `get_source` + read), and scope is **correct but more
expensive than grep** — because the answer (enum state names, process structure)
is *lost in lowering* and scope has to reconstruct it from source it can only
reach one range at a time:

| intent question | scope (out tok / turns) | grep (out tok / turns) | scope penalty |
|---|---|---|---|
| `uart-fsm-state-names` | 2271 / **11** | 493 / **3** | **3.7× turns, 4.6× out** |
| `cva6-ptw-fsm-states` | 1216 / **8** | 517 / **4** | 2× turns, 2.4× out |
| `uart-reset-polarity` | 1367 / **8** | 578 / **4** | 2× turns, 2.4× out |
| `cva6-reset-polarity` | 545 / **3** | 366 / **3** | ~tie (name-based heuristic carries it) |

(Numbers from `eval/results/uart_20260620-223408/summary.md` and
`eval/results/cva6-full_MERGED.md`.)

**Read of the data:** Phase 2's payoff is *not correctness* on these — scope
already gets them right. It is **cost**: collapsing an 8–11-turn source
reconstruction into a 1–2-turn direct query, so the intent class stops being the
one place scope loses to grep. The single sharpest signal is **FSM enum state
names** (`uart-fsm-state-names`: 11 turns) — the canonical Slang→Naja loss
(DESIGN.md §2). Reset polarity is a *weak* signal: the name-based heuristic in
`get_module_card` nearly closes it already (cv64 is a tie), so it does **not**
justify Phase 2 on its own.

**Conclusion:** the data justifies prototyping Phase 2, narrowly, against
enum/state-name and symbolic-parameter recovery — *not* a broad living-AST build.
It does not yet justify the naja C++ ownership refactor; that waits behind a
measured prototype win (§4).

**Update (2026-06-25) — the inline cases are now phase-1-solved; the gate moved.**
`get_source` gained a declaration-aware upward window (commit `f628622`): when a
register's declaration sits just below an inline `enum`/`struct`/`typedef`, that
block (its members) is pulled in. So `cva6-ptw-fsm-states` now passes reliably at
**7 turns** (was 9→13 max-turns→15) with *no* AST link — its enum is inline. The
inline FSM-state questions therefore **no longer justify Phase 2**; phase-1 reaches
them. The justification narrows to what source-windowing structurally *cannot*
reach: the new **`cva6-privlvl-enum`** gate, where the state type is a **package
typedef** (`riscv::priv_lvl_t`) whose members live in another file — scope **fails
it (0/1, max-turns)** while grep passes (4 turns). That, plus symbolic params and
process structure, is the real Phase-2 case.

## 2. What Phase 2 must buy, mapped to questions

| Phase-2 capability (DESIGN.md §2 "lost in lowering") | eval question it makes cheap | priority |
|---|---|---|
| enum/struct type names **declared in a package/typedef** (members in another file) | **`cva6-privlvl-enum`** — scope fails phase-1 (0/1, max-turns) | **P0** |
| symbolic parameter expressions (value kept, formula lost) | *new* questions to author (symbolic param meaning) | **P0** |
| process structure (which `always_ff`, sync/async reset, sensitivity) | `*-reset-polarity` (today name-based) | P1 |
| **inline** enum/struct names (declared next to the register) | `uart-fsm-state-names`, `cva6-ptw-fsm-states` — **phase-1-solved** by the declaration-aware `get_source` window; *not* a Phase-2 gate | — |
| assertions/SVA, packages/imports, generate provenance | none yet — defer until a question needs them | P2 |

`cva6-privlvl-enum` is the authored enum gate (package typedef). The bank still
has no *symbolic-parameter-meaning* question (DESIGN.md §9 calls for one);
authoring 2–3 is part of P2.0 so the gate has a second capability to move.

## 3. Prep-hook status (DESIGN.md §9 "prep hooks", cheap things done now)

- **Hook 2 — provider split: DONE.** `src/naja_scope/session.py` carries the
  `StructuralProvider` seam explicitly ("phase 2 adds an `IntentProvider` next to
  it"). Phase 2 plugs in here rather than rewriting tool handlers.
- **Hook 3 — `query_python` raw escape hatch: DONE** (`api.py`, gated/disabled by
  default). It is the telemetry surface for which intent queries agents reach for.
- **Hook 1 — `sv_symbol_path` persistent join key: NOT DONE** (a naja-side change,
  not this repo — record the slang hierarchical path as an RTL info at lowering,
  alongside the typed `SNLSourceLoc`). Still an open naja feature request; needed
  only for **cold-start** intent re-binding (warm sessions don't need it). File it
  before P2.2.

## 4. Milestones (gated — the prototype is the go/no-go for the C++ work)

DESIGN.md's sequence is "prototype with option 1, productize with option 2, hold
3 in reserve." Made concrete and gated:

### P2.0 — prototype (option 1: separate pyslang re-elaboration), zero naja C++
- Keep a `slang`/`pyslang` re-elaboration of the design alive in the warm server
  process, beside the SNL session. Build a *lossy* range-keyed
  `SNLDesignObject → slang Symbol` lookup (good enough for a prototype; exact
  coupling is P2.2's job).
- Add an `IntentProvider` behind the existing seam exposing **`get_fsm_states(reg)`**
  (enum names + encodings for a state register) and **`get_type(ref)`**; surface as
  one MCP tool (e.g. `get_intent`).
- Author 2–3 **symbolic-parameter-meaning** intent questions for the bank
  (`intent: true`), with goldens. (The enum gate `cva6-privlvl-enum` is already
  authored.)
- **GATE (the decision):** re-run the gate questions — **`cva6-privlvl-enum`**
  (package-typedef enum; scope currently **0/1, max-turns**) plus the new
  symbolic-param questions — with the IntentProvider enabled. Phase 2 proceeds
  **iff** `get_type`/`get_fsm_states` lets scope **answer them at ≤ grep's
  turns/tokens** (privlvl-enum: 0/1 → 1/1 within grep's ~4 turns). The *inline*
  FSM-state questions are **out of the gate** — phase-1 already solves them
  (`f628622`), so they no longer discriminate. If the intent layer doesn't beat
  grep on the package/symbolic cases, **stop** — the living AST isn't worth the
  productization cost, and that is a real outcome the eval was built to detect.
- Risks at this tier (DESIGN.md §"Exposure options" 1): double elaboration +
  memory; **divergence** if the prototype's slang version/flags differ from
  naja's fork → mismatched hierarchies. Mitigate by pinning the same slang commit;
  treat any hierarchy mismatch as a gate failure, not a bug to paper over.

### P2.1 — process structure
- Add `get_process(reg)` (which `always_ff`, sync vs async reset, sensitivity) so
  `*-reset-polarity` moves off the name-based heuristic to a structural answer.
  Lower priority — the heuristic already near-ties grep here.

### P2.2 — productize (option 2: Compilation inside naja.so, curated API)
- Only after P2.0 gate passes. The real engineering is the **exact coupling map**,
  not the layers: build `SNLDesignObject* ↔ const slang::ast::Symbol*` where
  `cloneRTLInfos` runs (uniquification is where naive range-keyed maps break —
  one InstanceBodySymbol → several SNL designs). Curated bindings:
  `get_type`, `get_parameters(symbolic=True)`, `get_process`, `find_assertions`.
- Ownership: move slang's `Compilation` off `SNLSVConstructor`'s `unique_ptr`
  member to a session-lifetime object (a contained refactor, not a redesign).
- Persist `sv_symbol_path` (hook 1) so cold-start (snapshot-loaded SNL, no live
  Compilation) degrades to "intent layer not loaded" but can re-bind on warm-up.
- Hold **option 3** (full pyslang interop across the module boundary) in reserve —
  only if option-2 usage proves the long tail is needed; it costs ABI/version
  lockstep between naja.so and pyslang.

## 5. Snapshot asymmetry (shapes the UX, non-negotiable)

SNL reloads from naja-if in seconds; a `Compilation` is bump-allocated,
pointer-rich, **never serializable** — re-elaboration only (minutes at scale). So
two tiers are inherent and the tools must say which they're in:
- **Cold start:** SNL from snapshot + persisted ranges. Intent tools degrade:
  *"source range provided; intent layer not loaded."*
- **Warm session:** SNL + living AST, full capability. A `load(intent=true/false)`
  knob; memory roughly doubles (each layer GB-class on CVA6-scale).

## 6. Non-goals (stay deferred regardless of Phase 2)

Slang-side graph store; LLM enrichment / summaries; protocol inference beyond
heuristics; multi-design servers; any graph database; GraphML. None are needed
for the intent win, and §5's Risk 5 (premature platform-building) applies.

## 7. Immediate next actions

1. File the `sv_symbol_path` naja feature request (hook 1) — cheap, unblocks P2.2
   cold-start later.
2. Author the symbolic-parameter intent questions in `eval/questions/` (the enum
   gate `cva6-privlvl-enum` is done; symbolic-param still needed for the second
   gate capability).
3. Build the P2.0 pyslang-re-elaboration prototype + `IntentProvider.get_type` /
   `get_fsm_states` behind the `session.py` seam; re-run the **gate questions**
   (`cva6-privlvl-enum` + symbolic-param). Decide from the number: does scope reach
   them at ≤ grep's cost?
