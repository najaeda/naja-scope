# Eval results (DESIGN.md §9, Week 3) — E3 write-up

Golden-answer questions answered two ways and compared on correctness, tokens,
and turns:
- **arm A (scope):** Claude Code with *only* the naja-scope MCP tools, against a
  warm server with the design preloaded. No source-file access.
- **arm B (grep):** Claude Code with *only* Bash/Read/Grep/Glob over the
  design's SystemVerilog source tree. No MCP.

Both arms pay the same Claude Code overhead, so the per-arm delta is the signal.
Runs on 2026-06-20 with `claude` 2.1.185, model claude-opus-4-8, max-turns 12.
Raw per-question JSON is under `eval/results/<design>_<timestamp>/` (gitignored).

## Headline

| design | arm | correct | input tok (incl. cache) | output tok | turns |
|---|---|---|---|---|---|
| UART (110-line fixture) | A (scope) | **9/9** | 21.2k | 8.0k | 54 |
| UART | B (grep) | 8/9 | 23.2k | 7.5k | 38 |
| CVA6 cv32a6_imac_sv32 (dev) | A (scope) | **12/13** | 1.05M | 18.7k | 79 |
| CVA6 cv32 | B (grep) | 6/13 | 1.89M | 30.4k | 90 |
| CVA6 cv64a6_imafdc_sv39 (**headline**) | A (scope) | **12/13** | 784k | 19.3k | 61 |
| CVA6 cv64 | B (grep) | 9/13 | 1.53M | 27.6k | 93 |

On the dev core, **scope doubled grep's accuracy (12/13 vs 6/13) while spending
~55% of its input tokens and ~60% of its output**. On the 110-line UART fixture
the two are a near-tie — exactly as predicted (DESIGN.md §4): grep is competitive
when the whole design fits in a couple of reads. The value is not a constant
multiplier; it is that grep *fails a class of question* that scale makes worse.

The **headline cv64a6_imafdc_sv39 run is 12/13 vs 9/13, and the token profile
holds** (scope spends ~0.51x grep's input, ~0.70x its output, in 0.66x the
turns). Grep does better here than on cv32 (9 vs 6) because its config is *more
greppable* (see "config delta" below). Scope's single miss is a genuine,
build-independent affordance gap — `cva6-top-submodules` (max-turns on the cv64
top's 4,866-way fan-out; Honest failures #4). The decisive post-elaboration class
(flattened counts, post-lowering drivers) is still scope-only: grep gets
`cva6-ex-seq-count`, `cva6-core-seq-count`, `cva6-div-state-driver`, and the
cross-hier cone wrong; scope gets all four right.

(The cone `cva6-div-cone-crosshier` initially scored a non-result because the
`trace_cone` call exceeded the agent's wall-clock budget under a **Debug** naja
build. After rebuilding naja in **Release** the same call dropped 840s->135s and
the agent answered correctly in 4 turns / 177s wall — naming `csr_regfile_i`
(`priv_lvl_q`, `mstatus_q`, `debug_mode_q`), `issue_stage_i` scoreboard, and the
wt D-cache miss-unit. That passing run is the one scored above.)

### cv64 config delta (why the goldens were re-verified)

The headline config differs from the dev config in **two structural ways**, not
just bit widths — both re-verified directly on the cv64 snapshot via
`eval/harness/probe_goldens.py` (ground truth out of the elaborated netlist):

1. **+FPU.** `imafdc` adds the F/D FPU (cvfpu) to EX. `cva6-ex-seq-count`
   92→**358**; `cva6-serdiv-adders` (64-bit datapath) 108→**206**.
2. **WT cache, not HPDCACHE.** `imafdc` uses the write-through `wt_dcache`
   subsystem; `imac` uses HPDCACHE. Consequences: `hpdcache_mux` **does not
   exist** on the headline, so the uniquification question was retargeted to
   `rr_arb_tree` (base + `__elab1..6` = **7** variants); `noc_req_o` is driven by
   the WT cache's AXI adapter (`...i_cache_subsystem.i_adapter.i_axi_shim`), not
   the hpdcache AXI arbiter; and whole-core seq count is **lower** (808→**573**)
   despite the FPU, because the WT cache is far less register-heavy than HPDCACHE.

Config-independent goldens re-confirmed unchanged on cv64: `cva6-commit-no-regs`
(0), `cva6-div-state-width` (2, driver still `naja_dffrn__w2` in serdiv.sv),
reset polarity (`rst_ni`, active-low), PTW FSM (3-bit, IDLE), and the divider
`state_d` cross-hier cone still reaches `csr_regfile_i` / `issue_stage_i`
scoreboard. The full cv32→cv64 diff is documented inline in `cva6.yaml`.

Snapshot built once (~48 min elaboration; 969k instances, clean load) and reused
across every arm-A run via the naja-if cache (reloads in ~80s) — the DESIGN.md §5
amortization. (Operational note: the run was interrupted twice by the **Claude
CLI subscription session limit** — not a naja/network fault — and the cv64
`trace_cone` call (slow under the **Debug** naja build) exceeded the agent's
budget on `cva6-div-cone-crosshier`; affected questions were re-run after the
limit reset. Per-question JSON lives across `eval/results/cva6-full_2026*`; the
authoritative merge is `eval/results/cva6-full_MERGED.md`.)

## Where scope wins, and why (CVA6)

Grep got 6 questions wrong; scope got all 6 right. They are precisely the
post-elaboration questions whose answer is not in the source text:

| question | category | grep | grep cost (out tok / turns) | why grep fails |
|---|---|---|---|---|
| cva6-commit-no-regs | structure | wrong | 5.0k / 13 (max-turns) | "does this subtree contain any register" needs the flattened netlist |
| cva6-ex-seq-count | structure | wrong | 9.5k / 12 (max-turns) | flattened FF-group count across the hierarchy |
| cva6-core-seq-count | structure | wrong | 1.0k / 5 | whole-core FF-group count |
| cva6-uniquify-mux | structure | wrong | 3.0k / 13 (max-turns) | uniquified module variants don't exist in source |
| cva6-div-state-driver | connectivity | wrong | 0.7k / 4 | which primitive drives a register (post-lowering) |
| cva6-serdiv-adders | structure | wrong | 0.6k / 5 | count of a lowered primitive (naja_fa) in a module |

Repeated shape: grep either **burns thousands of output tokens crawling files
and still answers wrong** (the max-turns rows), or gives up cheap and wrong.
"On MegaBoom-class designs grep isn't slow, it's wrong" (DESIGN.md §4) — here it
is frequently both. Scope answered each from `get_stats` / `get_hierarchy` /
`get_drivers` / `resolve` in a handful of turns.

## Where grep is competitive or cheaper (the phase-2 baseline)

The intent-class questions — answered the **phase-1 way** (source-range + read)
to baseline what a phase-2 living-AST layer would improve:

| question | arm A (scope) | arm B (grep) | note |
|---|---|---|---|
| cva6-reset-polarity | correct, 3 turns | correct, 3 turns | both read the always_ff; grep marginally cheaper |
| cva6-ptw-fsm-states | correct, 9 turns / 1.6k out | correct, 5 turns / 0.6k out | enum state names live in source; grep reads them directly |
| uart-fsm-state-names | correct, 11 turns / 2.3k out | correct, 3 turns | scope works hard to recover what is lost in lowering |

This is the honest result: when the answer is a readable enum or `always_ff`,
reading source beats structural lookup, and scope's phase-1 structural layer
*loses on cost*. It is the data that justifies (does not yet build) the phase-2
intent layer — recovering enum/state names, symbolic params, and process
structure so these questions stop costing scope extra turns. Source back-links
(`cva6-ptw-source`) were correct and cheap for both arms — scope's `get_source`
lands on the exact range, grep finds it too on a navigable tree.

## Honest failures / to-dos

1. ~~**`cva6-div-cone-crosshier` defeated both arms** (max-turns 12, no
   answer).~~ **FIXED.** The original failure was a tool/affordance gap, not a
   grep win: the agent burned the turn budget re-deriving each frontier path's
   subtree by hand against a multi-KB node dump. `trace_cone` now returns a
   `cross_hierarchy` block that groups the stop-at-flops frontier by top-level
   submodule and, under `outside_root_subtree`, names the frontier registers
   outside the cone root's own subtree directly (counts + a few example paths,
   token-bounded per DESIGN.md §4). The agent reads the cross-hier answer
   (`csr_regfile_i`, `issue_stage_i`, incl. `priv_lvl_q`) straight out of it.
   NOTE (2026-06-22): the cone tool was since rebuilt on naja's native
   `SNLLogicalCone` (najaeda 0.7.6) — the hand-rolled equipotential traversal and
   its `frontier_summary` are gone, replaced by `cross_hierarchy` over the native
   DAG's flop frontier; the cross-hier dependency is unchanged design truth. The
   native cone reaches a much larger frontier than the old walk (196 vs 16 flops
   on state_d). RECONCILED 2026-06-22 (NAJAEDA_NOTES.md §7): 196 is the TRUE
   combinational fan-in and the naja arc model is precise (`naja_mem` RDATA←RADDR
   only, no all-to-all) — the old equipotential walk under-traced (never crossed
   the hierarchical flush/control fabric, so 16 ⊂ 196). The frontier is dominated
   by the global flush network the divider's `state_d` legitimately samples; that
   is a summarisation/UX concern, not a modeling defect. Regression: `cone.py` +
   `tests/test_zzz_cone_cva6.py` and `test_cone_cross_hierarchy_summary`.
2. **`in_tok` understates grep's cost.** The bulk is cache-read source
   (1.88M for grep vs 1.04M for scope on cv32; 1.53M vs 0.76M on cv64); even
   discounted, it is the context bloat the tool layer avoids, and it grows with
   design size while scope's stays roughly flat.
3. ~~**(cv64) `cva6-div-cone-crosshier` is INDETERMINATE.**~~ **RESOLVED — it
   was a Debug-build artifact.** The cone first scored a non-result because the
   `trace_cone` call (8,555 native DAG nodes) exceeded the agent's wall-clock
   budget under a **Debug** naja build, where the call wall-clocked ~840s — an
   invalid timing. After rebuilding naja in **Release** the same call dropped to
   **135s** (~6.2x; identical result, 16 flops outside EX), and the live agent
   answered **correctly in 4 turns / 177s wall** over the MCP-SSE transport
   (`csr_regfile_i` priv_lvl/mstatus/debug, `issue_stage_i` scoreboard/fu_data, wt
   D-cache miss-unit). So the question is a clean pass on cv64 and there is **no
   `SNLLogicalCone` perf defect** — the apparent "perf to-do" was purely the Debug
   build. Lesson logged: never read wall-clock off the Debug dev build (see
   CLAUDE.md / NAJAEDA_NOTES.md). 135s is still a heavy single tool call, so a
   `max_frontier`/time cap remains a *nice-to-have* for even larger cones, but it
   is no longer a blocker. On the dev cv32 core the question also passes.
4. **(cv64) `cva6-top-submodules` blows scope's turn budget — a real,
   build-independent affordance gap.** This one is *not* timing: it fails on
   **max-turns** (a step count), reproduced across two clean runs, so a Release
   build will not change it. Measured on the cv64 snapshot, the top (`cva6`) has
   **4,866 direct children = 4,842 `assign` + 14 leaves + only 10 real
   submodules** (the golden: frontend, id_stage, issue_stage, ex_stage,
   commit_stage, csr_regfile, perf_counters, controller, wt_cache_subsystem,
   cva6_rvfi_probes). The agent's natural tool, `get_hierarchy(depth=1)`, returns
   `children_total=4866` but a **token-bounded window of only 20 children with
   `children_truncated=4846`, no pagination cursor, and no kind/model filter** —
   and since 99.5% of children are `assign` glue, that 20-row window is swamped by
   assigns and the 10 real submodules are not reachable through it. So the agent
   burns its 12 turns trying and never converges. Grep answers it by reading the
   top module text. The fix is small and already half-built: `get_stats()` on the
   top already returns `children_by_model` = exactly those 10 real submodules (no
   assigns, no leaves) — so either steer the agent there, or add a
   "real-children-only" filter (and a real cursor) to `get_hierarchy`. Scope
   passes this on cv32, where the top fan-out is far smaller; it is purely
   scale-driven.
5. **(cv64) grep's `cva6-uniquify-mux` pass is soft.** Retargeted to
   `rr_arb_tree` (7 variants), grep "passed" by enumerating distinct source
   `#(...)` parameterizations and *fabricating* the `__elab1..6` names (an
   elaboration artifact it cannot see). The count happens to be derivable from
   source here, so the deterministic check credits it — but it is a confident,
   partly-hallucinated answer, exactly the failure mode scope avoids by reading
   the elaborated netlist. The original `hpdcache_mux` (20 variants) was *not*
   source-derivable and grep failed it honestly on cv32; the cv64 retarget is
   more grep-tractable. Discounting this soft pass, grep is effectively 8/13.

## Verdict

Go — confirmed on the headline config. On cv64a6_imafdc_sv39 scope leads **12/13
vs grep 9/13** at ~0.51x input / ~0.70x output tokens, in 0.66x the turns; on the
dev cv32 config the gap is wider (12/13 vs 6/13). The decisive, scope-only class
is unchanged: flattened sequential counts, post-lowering drivers, and the
cross-hierarchy cone (`cva6-ex-seq-count`, `cva6-core-seq-count`,
`cva6-div-state-driver`, `cva6-div-cone-crosshier`) that grep gets wrong or
hallucinates. The cv64 run surfaced exactly **one genuine, build-independent
affordance gap** the smaller dev core hid — top-level fan-out (#4: `get_hierarchy`
truncates the 4,866-child top with no filter, while `get_stats.children_by_model`
already has the answer) — and one false alarm now closed (#3: the cone "timeout"
was a Debug-build artifact; a Release rebuild brought it to a clean pass). Neither
is a correctness failure. The numeric goldens are re-verified against the headline
config (cv32→cv64 deltas documented in `cva6.yaml`), closing the DESIGN.md §9
eval gate.
