#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Week-3 eval orchestrator (DESIGN.md §9): naja-scope MCP vs plain grep.

For each golden question, run two arms headlessly and record correctness,
tokens, and turns:
  arm A (scope): `claude -p` with ONLY the naja-scope MCP tools (warm server),
                 no source-file access.
  arm B (grep):  `claude -p` with ONLY Bash/Read/Grep/Glob over the design's
                 source tree, no MCP.

The two arms pay the same Claude Code system-prompt overhead, so the per-arm
delta in tokens/turns is the meaningful signal.

Usage:
  # validate bank + scoring + commands without spending anything / needing CLI:
  python run_eval.py --design uart --arm both --dry-run

  # real run (needs the `claude` CLI; --claude-bin or $CLAUDE_BIN or PATH):
  python run_eval.py --design uart --arm both --out eval/results

Arm A starts a warm SSE naja-scope server (serve.py), loads the design once,
and points Claude Code's MCP client at it. The load cost (~12s cva6-small /
~29s cva6-full on najaeda 0.7.8) is paid once and shared by every arm-A question.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import designs as design_registry  # noqa: E402
import score as scoring  # noqa: E402

REPO = os.path.dirname(os.path.dirname(HERE))

# Query tools only: the design is preloaded into the warm server, so the agent
# must not reload/reset it.
SCOPE_TOOLS = [
    "status", "resolve", "find", "get_hierarchy", "get_drivers", "get_loads",
    "trace_cone", "get_source", "get_module_card", "get_stats", "get_intent",
    "query_python",
]
ARM_A_ALLOWED = ",".join(f"mcp__naja-scope__{t}" for t in SCOPE_TOOLS)
ARM_B_ALLOWED = "Bash,Read,Grep,Glob"
ARM_A_DISALLOWED = "Bash,Read,Edit,Write,Glob,Grep,WebFetch,WebSearch,Task"

SHARED_SYS = ("End your reply with a single line of the form "
              "'ANSWER: <concise answer>'.")
ARM_A_SYS = ("You are answering a question about an elaborated SystemVerilog "
             "netlist using ONLY the naja-scope MCP tools (resolve, get_drivers, "
             "trace_cone, get_source, get_module_card, get_stats, find, "
             "get_hierarchy, and get_intent for source-level type/enum/parameter "
             "facts the netlist erases in lowering). Do NOT read RTL source files "
             "directly. " + SHARED_SYS)
ARM_B_SYS = ("You are answering a question about a SystemVerilog design by "
             "searching and reading its source tree under the current directory "
             "with grep/ripgrep and file reads. " + SHARED_SYS)


def _apply_config(q: dict, design_key: str) -> dict:
    """Resolve per-config overrides on a question.

    A CVA6 question may carry `by_config: {<design_key>: {question?, golden?,
    check?}}` to specialize the fields that differ between configs (cv32a6 dev vs
    cv64a6 headline) — numeric counts, or a whole retargeted question. The base
    fields are the default (the headline cv64a6_imafdc_sv39 values); an entry
    keyed by `design_key` overrides them. Returns a copy without `by_config`."""
    by = q.get("by_config") or {}
    merged = {k: v for k, v in q.items() if k != "by_config"}
    if design_key in by:
        merged.update(by[design_key])
    return merged


def load_bank(design_key: str) -> list:
    spec = design_registry.get(design_key)
    with open(spec["questions"], encoding="utf-8") as f:
        bank = yaml.safe_load(f)
    return [_apply_config(q, design_key) for q in (bank.get("questions") or [])]


def resolve_claude_bin(arg: str | None) -> str | None:
    return arg or os.environ.get("CLAUDE_BIN") or shutil.which("claude")


def build_cmd(claude_bin, arm, prompt, mcp_config_path, max_turns):
    cmd = [claude_bin, "-p", prompt, "--output-format", "json",
           "--max-turns", str(max_turns)]
    if arm == "A":
        cmd += ["--mcp-config", mcp_config_path,
                "--allowedTools", ARM_A_ALLOWED,
                "--disallowedTools", ARM_A_DISALLOWED,
                "--append-system-prompt", ARM_A_SYS]
    else:
        cmd += ["--allowedTools", ARM_B_ALLOWED,
                "--append-system-prompt", ARM_B_SYS]
    return cmd


def parse_claude_json(stdout: str) -> dict:
    """Defensive parse of `claude -p --output-format json` output."""
    try:
        obj = json.loads(stdout)
    except json.JSONDecodeError:
        # Some versions stream NDJSON; take the last JSON object line.
        obj = None
        for line in reversed(stdout.strip().splitlines()):
            try:
                obj = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
        if obj is None:
            return {"result": stdout, "_parse_error": True}
    usage = obj.get("usage", {}) or {}
    return {
        "result": obj.get("result") or obj.get("text") or "",
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cache_read_tokens": usage.get("cache_read_input_tokens"),
        "num_turns": obj.get("num_turns"),
        "cost_usd": obj.get("total_cost_usd"),
        "is_error": obj.get("is_error"),
        "raw": obj,
    }


# -- warm server (arm A) -------------------------------------------------------

class WarmServer:
    def __init__(self, design_key, host, port, ready_timeout,
                 refresh_cache=False, intent=False):
        self.design_key, self.host, self.port = design_key, host, port
        self.ready_timeout = ready_timeout
        self.refresh_cache = refresh_cache
        self.intent = intent
        self.proc = None
        self.ready = None
        self.ready_file = tempfile.mktemp(suffix=".ready.json")

    def url(self):
        return f"http://{self.host}:{self.port}/sse"

    def mcp_config(self):
        cfg = {"mcpServers": {"naja-scope": {"type": "sse", "url": self.url()}}}
        path = tempfile.mktemp(suffix=".mcp.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        return path

    def start(self):
        if os.path.exists(self.ready_file):
            os.remove(self.ready_file)
        cmd = [sys.executable, os.path.join(HERE, "serve.py"),
               "--design", self.design_key, "--transport", "sse",
               "--host", self.host, "--port", str(self.port),
               "--ready-file", self.ready_file]
        if self.refresh_cache:
            cmd.append("--refresh-cache")
        if self.intent:
            cmd.append("--intent")
        print(f"[warm] starting: {' '.join(cmd)}", file=sys.stderr)
        self.proc = subprocess.Popen(cmd, env=os.environ.copy())
        t0 = time.time()
        while time.time() - t0 < self.ready_timeout:
            if self.proc.poll() is not None:
                raise RuntimeError("warm server exited before becoming ready")
            if os.path.exists(self.ready_file):
                try:
                    with open(self.ready_file) as f:
                        self.ready = json.load(f)
                    break
                except (json.JSONDecodeError, OSError):
                    pass
            time.sleep(2)
        else:
            self.stop()
            raise TimeoutError(
                f"warm server not ready in {self.ready_timeout}s")
        print(f"[warm] ready: {self.ready.get('label')} "
              f"({self.ready.get('load_seconds')}s)", file=sys.stderr)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


# -- run -----------------------------------------------------------------------

def run_one(claude_bin, arm, q, cwd, mcp_config_path, max_turns):
    prompt = q["question"].strip()
    cmd = build_cmd(claude_bin, arm, prompt, mcp_config_path, max_turns)
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    parsed = parse_claude_json(proc.stdout)
    parsed["wall_seconds"] = round(time.time() - t0, 1)
    parsed["stderr_tail"] = proc.stderr[-500:] if proc.stderr else ""
    verdict = scoring.score(parsed["result"], q["check"])
    parsed["correct"] = verdict
    parsed["needs_judge"] = verdict is None
    parsed["arm"], parsed["id"] = arm, q["id"]
    return parsed


def dry_run(design_key, bank, arms, claude_bin):
    spec = design_registry.get(design_key)
    print(f"\n=== DRY RUN: {spec['label']} ({len(bank)} questions) ===")
    print(f"claude binary: {claude_bin or 'NOT FOUND (set --claude-bin or $CLAUDE_BIN)'}")
    print(f"arm B cwd (grep): {spec['source_root']}")
    print(f"arm A: warm SSE server, load={spec['load']}, env={spec['env'] or '{}'}")
    # Self-test: each golden answer must satisfy its own deterministic check.
    print("\n-- golden self-test (golden answer vs its own check) --")
    bad = 0
    for q in bank:
        if scoring.needs_judge(q["check"]):
            print(f"  [judge] {q['id']}: deferred to LLM judge")
            continue
        ok = scoring.score("ANSWER: " + q["golden"], q["check"])
        flag = "ok " if ok else "FAIL"
        if not ok:
            bad += 1
        print(f"  [{flag}] {q['id']} ({q['category']})")
    # Show one example command per arm.
    if bank:
        ex = bank[0]["question"].strip()
        print("\n-- example commands --")
        for arm in arms:
            cmd = build_cmd(claude_bin or "claude", arm, ex,
                            "<mcp_config.json>", 12)
            print(f"  arm {arm}: {' '.join(repr(c) if ' ' in c else c for c in cmd)}")
    print(f"\nGolden self-test: {len(bank) - bad} ok, {bad} FAIL "
          "(FAIL means the golden answer doesn't satisfy its own check -- fix the check).")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--design", required=True, choices=list(design_registry.DESIGNS))
    ap.add_argument("--arm", default="both", choices=["A", "B", "both"])
    ap.add_argument("--ids", nargs="*", help="only these question ids")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=os.path.join(REPO, "eval", "results"))
    ap.add_argument("--claude-bin", default=None)
    ap.add_argument("--max-turns", type=int, default=12)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--warm-ready-timeout", type=int, default=4500)
    ap.add_argument("--refresh-cache", action="store_true",
                    help="force arm-A warm server to re-elaborate (ignore snapshot cache)")
    ap.add_argument("--intent", action="store_true",
                    help="load the warm intent layer so arm A can call get_intent "
                         "(phase-2 gate). Off by default (phase-1 baseline).")
    args = ap.parse_args()

    bank = load_bank(args.design)
    if args.ids:
        bank = [q for q in bank if q["id"] in set(args.ids)]
    if not bank:
        print("No questions selected (cva6.yaml is empty until E2).",
              file=sys.stderr)
    arms = ["A", "B"] if args.arm == "both" else [args.arm]
    claude_bin = resolve_claude_bin(args.claude_bin)

    if args.dry_run:
        sys.exit(1 if dry_run(args.design, bank, arms, claude_bin) else 0)

    if not claude_bin:
        sys.exit("No `claude` binary found. Pass --claude-bin or set $CLAUDE_BIN.")
    if not bank:
        sys.exit(0)

    spec = design_registry.get(args.design)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = os.path.join(args.out, f"{args.design}_{stamp}")
    os.makedirs(outdir, exist_ok=True)

    warm = mcp_config_path = None
    scratch = os.path.join(REPO, "eval", ".scratch")
    os.makedirs(scratch, exist_ok=True)
    results = []
    try:
        if "A" in arms:
            warm = WarmServer(args.design, args.host, args.port,
                              args.warm_ready_timeout,
                              refresh_cache=args.refresh_cache,
                              intent=args.intent)
            warm.start()
            mcp_config_path = warm.mcp_config()
        for q in bank:
            for arm in arms:
                cwd = scratch if arm == "A" else spec["source_root"]
                print(f"[run] {q['id']} arm {arm} ...", file=sys.stderr)
                r = run_one(claude_bin, arm, q, cwd, mcp_config_path,
                            args.max_turns)
                results.append(r)
                with open(os.path.join(outdir, f"{q['id']}_{arm}.json"),
                          "w", encoding="utf-8") as f:
                    json.dump(r, f, indent=2, default=str)
    finally:
        if warm:
            warm.stop()

    write_summary(outdir, spec, bank, results)
    print(f"\nResults: {outdir}")


def write_summary(outdir, spec, bank, results):
    by = {(r["id"], r["arm"]): r for r in results}
    lines = [f"# Eval: {spec['label']}", ""]
    lines.append("| id | category | arm | correct | in_tok | out_tok | turns | cost |")
    lines.append("|---|---|---|---|---|---|---|---|")
    agg = {}
    for q in bank:
        for arm in ("A", "B"):
            r = by.get((q["id"], arm))
            if not r:
                continue
            c = {True: "Y", False: "N", None: "?"}[r["correct"]]
            lines.append(
                f"| {q['id']} | {q['category']} | {arm} | {c} | "
                f"{r.get('input_tokens')} | {r.get('output_tokens')} | "
                f"{r.get('num_turns')} | {r.get('cost_usd')} |")
            a = agg.setdefault(arm, {"n": 0, "correct": 0, "in": 0, "out": 0, "turns": 0})
            a["n"] += 1
            a["correct"] += 1 if r["correct"] else 0
            for k, kk in (("in", "input_tokens"), ("out", "output_tokens"),
                          ("turns", "num_turns")):
                a[k] += r.get(kk) or 0
    lines += ["", "## Aggregate", "",
              "| arm | n | correct | tot_in | tot_out | tot_turns |",
              "|---|---|---|---|---|---|"]
    for arm, a in sorted(agg.items()):
        lines.append(f"| {arm} | {a['n']} | {a['correct']} | {a['in']} | "
                     f"{a['out']} | {a['turns']} |")
    with open(os.path.join(outdir, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(outdir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({"results": results}, f, indent=2, default=str)


if __name__ == "__main__":
    main()
