# Reproducible agent comparison

This harness compares **agent + naja-scope** with **the same agent + source
search/read tools**. It supports repeatable OpenAI Codex and Anthropic Claude
Code model entries and records enough context to audit each run.

The figures currently shown in the project README came from an older,
single-model experiment. They are historical preliminary results, not output
from this harness. Publish new headline figures only after running this protocol
from a pinned, clean source revision with multiple repetitions.

## Fairness contract

For every requested model, both arms receive the identical question, exact
design label, source revision, top, file list, configuration, and elaboration
environment. Every question starts a fresh non-persistent agent session. Runs
are arranged in adjacent per-model/per-question arm pairs; which arm goes first
is randomized from the recorded seed.

The source arm is intentionally strong. It gets the entire source checkout and
may use `rg`/`grep`, file reads, `find`, `git`, `awk`/`sed`, shell pipelines, and
read-only scripts. The prompt tells it to follow the file list, includes,
defines, package imports, generate conditions, and parameter propagation. The
default Claude limit is 24 turns, rather than the old experiment's 12. A
15-minute wall timeout applies to either arm by default.

The source arm may not call naja-scope or substitute another elaborator,
synthesizer, simulator, or netlist database: that would test two structural
databases rather than “source analysis.” It may use a generated artifact only
when metadata proves the artifact came from the exact revision and
configuration under test. When source does not determine a post-elaboration
fact, the best answer is to identify that limitation instead of guessing.

The scope arm gets only the preloaded naja-scope MCP tools. With Claude Code,
this is enforced by the CLI tool allowlist. Codex currently runs in a
read-only sandbox and is instructed to use only the MCP server; any shell tool
event makes the result invalid. Full event traces are retained for audit.

This CVA6 bank is deliberately a **post-elaboration challenge set**, not a
representative sample of all RTL questions. Report results using that name; do
not generalize its accuracy gap to ordinary source-local work.

## Run it

Prerequisites are a clean CVA6 checkout, a working local naja-scope/najaeda
installation, and the provider CLIs whose models you want to test. Model IDs
are passed verbatim to the corresponding CLI.

First validate the matrix without loading CVA6 or spending model credits:

```bash
python benchmarks/run_comparison.py \
  --config benchmarks/cva6-cv32.json \
  --source-root /path/to/cva6 \
  --agent anthropic:<claude-model-a> \
  --agent anthropic:<claude-model-b> \
  --agent openai:<openai-model-a> \
  --agent openai:<openai-model-b> \
  --repetitions 3 \
  --dry-run
```

Then remove `--dry-run` to execute it. A real run starts one warm design server
and reuses that exact session for every scope-arm question. The included bank
pins CVA6 commit `e6473dd61f43168c86260052aecbd8143f36a8b3`; the runner refuses a
different revision or a dirty tree. `--allow-dirty` exists for local
development and records that state in the results.

Use repeatable `--agent` arguments to compare as many installed models as
needed, for example two Anthropic models and two OpenAI models. Each model is
always compared with itself across both arms; cross-provider token counts are
shown but should not be treated as directly equivalent.

## What is recorded

Each timestamped result directory contains:

- the expanded design config, design and harness revisions/dirty state,
  configuration fingerprint, provider, requested model ID, CLI executable and
  version, Python/naja-scope/najaeda/MCP versions, effort, budgets, and random
  seed;
- a full JSONL agent trace and final-answer file for every run;
- all provider-reported model usage, including Claude helper-model/cache usage;
- extracted tool calls and any isolation violation;
- deterministic pass/fail checks, with answers that cannot be machine-scored
  marked for review rather than silently counted as failures; and
- `summary.md`/`summary.json`, split by provider, requested model, and arm.

The primary comparison is paired accuracy and resource use **within the same
model**. Run at least three repetitions and manually adjudicate every `review`
or `invalid` item before publishing aggregate numbers.
