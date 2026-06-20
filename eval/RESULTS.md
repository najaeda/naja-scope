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
| CVA6 cv32a6_imac_sv32 | A (scope) | **12/13** | 1.05M | 18.7k | 79 |
| CVA6 | B (grep) | 6/13 | 1.89M | 30.4k | 90 |

On the real elaborated core, **scope doubled grep's accuracy (12/13 vs 6/13)
while spending ~55% of its input tokens and ~60% of its output**. On the
110-line UART fixture the two are a near-tie — exactly as predicted (DESIGN.md
§4): grep is competitive when the whole design fits in a couple of reads. The
value is not a constant multiplier; it is that grep *fails a class of question*
that scale makes worse.

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

1. **`cva6-div-cone-crosshier` defeated both arms** (max-turns 12, no answer).
   Scope *should* win this — the whole point of `trace_cone` is the
   cross-hierarchy flop frontier — but the agent did not converge in budget.
   Likely the cone response needs to surface the out-of-EX frontier registers
   more directly (and/or the eval needs a higher turn budget for cone
   questions). This is a tool/affordance gap, not a grep win.
2. **`in_tok` understates grep's cost.** The bulk is cache-read source
   (1.88M for grep vs 1.04M for scope); even discounted, it is the context
   bloat the tool layer avoids, and it grows with design size while scope's
   stays roughly flat.

## Verdict

Go. On the large design the win is decisive for the connectivity / structure /
uniquification class that motivated the project, with a clean ~2x accuracy and
~0.55x token profile. The small-design near-tie and the intent-question cost are
expected and honest, and they scope phase 2 rather than undercut phase 1. Next:
re-verify the numeric goldens against `cva6-full` (cv64a6_imafdc_sv39; widths
and counts differ) and run the headline once; fix the cone affordance behind
`cva6-div-cone-crosshier` before re-scoring that question.
