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
- **E2b (needs `claude` CLI):** run both arms on UART + `cva6-small`. Each arm-A
  run reuses the cached snapshot (~20 s warm start). Spends Claude usage.
- **E3:** write up correctness/token/turn deltas by category and design,
  including the intent-question baseline that justifies/kills phase 2. Re-verify
  numeric goldens against `cva6-full` before the headline run (config differs).

## Notes

- najaeda 0.7.4 fixes SV-snapshot reload, so the warm server elaborates a
  design once, caches a naja-if snapshot under `eval/.cache/<design>/`, and
  reloads it in seconds on every later start (DESIGN.md §5). Pass
  `--refresh-cache` to force re-elaboration after the source tree changes.
  The warm server is still loaded once and shared across all arm-A questions —
  never re-spawn it per question.
- Agents are told to end with `ANSWER: <...>`; scoring reads that line.
