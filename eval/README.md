# naja-scope eval (DESIGN.md §9, Week 3)

Golden-answer questions answered two ways and compared on **correctness,
tokens, and turns**:

- **arm A (scope):** Claude Code with *only* the naja-scope MCP tools, against a
  warm server that has the design preloaded. No source-file access.
- **arm B (grep):** Claude Code with *only* Bash/Read/Grep/Glob over the design's
  SystemVerilog source tree. No MCP.

Both arms pay the same Claude Code overhead, so the per-arm delta is the signal.
UART is the harness-validation + honest baseline (grep is competitive on a
110-line file); the decisive token win is expected on CVA6 (DESIGN.md §4).

## Layout

```
eval/
  harness/
    designs.py     design registry (load spec, source root, env, question bank)
    serve.py       warm naja-scope server: load a design once, serve over SSE/stdio
    score.py       deterministic checks (+ LLM-judge rubric for open-ended)
    run_eval.py    orchestrator: run both arms per question, score, summarize
  questions/
    uart.yaml      verified UART golden answers
    cva6.yaml      CVA6 bank (filled in E2 against the live core; empty until then)
  results/         per-run outputs (gitignored)
```

## Prerequisites

- The project venv with najaeda (`./.venv`), per the repo README.
- The `claude` CLI for real runs — pass `--claude-bin` or set `$CLAUDE_BIN`
  (not required for `--dry-run`).
- CVA6 source at `/Users/xtof/WORK/cva6` (the `cva6-grenoble` checkout's
  hpdcache submodule is uninitialized — do not use it). Designs `cva6-small`
  (cv32a6_imac_sv32, ~12–13 min first elaboration, then ~20 s from the snapshot
  cache) and `cva6-full` (cv64a6_imafdc_sv39, ~68 min first elaboration).

## Run

```bash
# 1. validate the question bank, scoring, and the exact arm commands -- no CLI,
#    no Claude usage spent. Also self-tests every golden answer against its check.
./.venv/bin/python eval/harness/run_eval.py --design uart --arm both --dry-run

# 2. real UART run (cheap; loads in <1s):
CLAUDE_BIN=/path/to/claude \
  ./.venv/bin/python eval/harness/run_eval.py --design uart --arm both

# 3. CVA6 dev run (small config; warm server elaborates ~12-13 min the first
#    time, then reloads in ~20s from eval/.cache/cva6-small on later runs):
CLAUDE_BIN=/path/to/claude \
  ./.venv/bin/python eval/harness/run_eval.py --design cva6-small --arm both

# headline run: --design cva6-full  (first elaboration ~68 min, then cached)
# pass --refresh-cache to force re-elaboration after the CVA6 source changes
```

Outputs land in `eval/results/<design>_<timestamp>/`: one JSON per
question×arm, plus `summary.md` (per-question table + aggregate) and
`summary.json`.

## Phasing

- **E1 (done):** harness + UART bank (verified) + scoring + warm server.
- **E2a (done):** snapshot-cached warm server (najaeda 0.7.4) + CVA6 bank
  authored and verified against the live `cva6-small` core (13 questions, every
  golden answer produced by the tools, not grep; see `questions/cva6.yaml`).
- **E2b (done):** ran both arms on UART (9 Q) and `cva6-small` (13 Q) on
  2026-06-20 (claude 2.1.185, opus-4-8). Headline: scope 12/13 vs grep 6/13 on
  CVA6, at ~0.55x input tokens; near-tie on UART. Raw JSON under
  `eval/results/` (gitignored).
- **E3 (done):** write-up in `eval/RESULTS.md` — deltas by category/design, the
  intent-question phase-2 baseline, and honest failures.
- **E4 (done, 2026-06-23):** ran the headline `cva6-full` (cv64a6_imafdc_sv39).
  Numeric goldens re-verified against that config (cv32→cv64 deltas documented
  inline in `questions/cva6.yaml` and `RESULTS.md`) via `probe_goldens.py`; the
  two affordance gaps the larger config surfaced were both closed and their
  questions re-scored — `trace_cone`'s cross-hierarchy frontier
  (`cva6-div-cone-crosshier`) and `get_hierarchy`'s non-assign filter for the
  4,866-child top (`cva6-top-submodules`). Final headline: **scope 13/13 vs grep
  9/13** at ~0.51x input / ~0.70x output tokens, 0.66x turns. Authoritative merge
  in `results/cva6-full_MERGED.md`; write-up in `RESULTS.md`. The DESIGN.md §9
  eval gate is closed — verdict **Go**.

## Notes

- najaeda 0.7.4 fixes SV-snapshot reload, so the warm server elaborates a
  design once, caches a naja-if snapshot under `eval/.cache/<design>/`, and
  reloads it in seconds on every later start (DESIGN.md §5). Pass
  `--refresh-cache` to force re-elaboration after the source tree changes.
  The warm server is still loaded once and shared across all arm-A questions —
  never re-spawn it per question.
- Agents are told to end with `ANSWER: <...>`; scoring reads that line.
- `questions/cva6.yaml` is **config-aware**: base fields are the cv64a6_imafdc_sv39
  headline values, and a question may carry a `by_config: {cva6-small: {...}}`
  block that `run_eval._apply_config` merges by design key at load time. So one
  bank scores both `--design cva6-full` (cv64) and `--design cva6-small` (cv32)
  against their own goldens — the four config-dependent questions (ex/core seq
  counts, serdiv adders, the uniquify-mux target) differ between them.
