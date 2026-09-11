#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fair, auditable agent comparison: naja-scope versus source analysis.

The runner deliberately separates the agent provider from the tool arm.  Every
configured model runs both arms with the same question, design context, process
environment, timeout, reasoning effort, and (where supported) turn limit.

Supported agent CLIs:
  anthropic:<model>  -> Claude Code (`claude -p`)
  openai:<model>     -> Codex CLI (`codex exec`)

Real runs spend model credits.  Use --dry-run to validate the matrix, scoring,
commands, repository revision, and design configuration without starting an
agent or loading the design.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
from importlib import metadata as importlib_metadata
import json
import os
from pathlib import Path
import platform
import random
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Iterable


HERE = Path(__file__).resolve().parent
REPO = HERE.parent

SCOPE_TOOLS = [
    "status", "resolve", "find", "get_hierarchy", "get_drivers",
    "get_loads", "trace_cone", "get_source", "get_module_card",
    "get_stats", "get_intent",
]
CLAUDE_SCOPE_ALLOWED = ",".join(
    f"mcp__naja-scope__{name}" for name in SCOPE_TOOLS)
CLAUDE_SCOPE_DENIED = ",".join(
    ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "WebFetch",
     "WebSearch", "Task"])


@dataclass(frozen=True)
class AgentSpec:
    provider: str
    model: str

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model}"


def parse_agent_spec(text: str) -> AgentSpec:
    provider, sep, model = text.partition(":")
    if not sep or not provider or not model:
        raise argparse.ArgumentTypeError(
            "agent must be PROVIDER:MODEL, for example "
            "anthropic:claude-sonnet-4-6")
    provider = provider.lower()
    if provider not in {"anthropic", "openai"}:
        raise argparse.ArgumentTypeError(
            f"unsupported provider {provider!r}; use anthropic or openai")
    return AgentSpec(provider, model)


def _expand(value: Any, source_root: Path) -> Any:
    if isinstance(value, str):
        return value.replace("${SOURCE_ROOT}", str(source_root))
    if isinstance(value, list):
        return [_expand(item, source_root) for item in value]
    if isinstance(value, dict):
        return {key: _expand(item, source_root) for key, item in value.items()}
    return value


def load_config(path: Path, source_root: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    config = _expand(config, source_root.resolve())
    required = {"id", "label", "load", "environment", "questions"}
    missing = sorted(required - set(config))
    if missing:
        raise ValueError(f"design config lacks: {', '.join(missing)}")
    if not config["questions"]:
        raise ValueError("design config has no questions")
    return config


def git_metadata(path: Path) -> dict[str, Any]:
    def run(*args: str) -> str:
        proc = subprocess.run(
            ["git", "-C", str(path), *args], capture_output=True, text=True)
        return proc.stdout.strip() if proc.returncode == 0 else ""

    revision = run("rev-parse", "HEAD")
    dirty_lines = run("status", "--short").splitlines()
    return {
        "revision": revision or None,
        "dirty": bool(dirty_lines),
        "dirty_paths": len(dirty_lines),
        "dirty_status": dirty_lines,
    }


def config_fingerprint(config: dict[str, Any], source: dict[str, Any]) -> str:
    design = {key: config.get(key) for key in (
        "id", "label", "configuration", "load", "environment")}
    material = json.dumps(
        {"design": design, "source": source}, sort_keys=True,
        separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def design_context(config: dict[str, Any], source: dict[str, Any]) -> str:
    load = config["load"]
    env = config.get("environment", {})
    lines = [
        f"Design: {config['label']} (id={config['id']})",
        f"Source revision: {source.get('revision') or 'unrecorded'}",
        f"Source tree dirty: {source.get('dirty', False)}",
        f"Top module: {load.get('top')}",
        f"Configuration: {config.get('configuration', 'unspecified')}",
        f"File list: {load.get('flist')}",
        "Elaboration environment:",
    ]
    lines.extend(f"  {key}={value}" for key, value in sorted(env.items()))
    if config.get("source_guidance"):
        lines.append("Source-analysis guidance:")
        lines.extend(f"  - {item}" for item in config["source_guidance"])
    if config.get("excluded_artifacts"):
        lines.append("Artifacts that are not evidence for this configuration:")
        lines.extend(f"  - {item}" for item in config["excluded_artifacts"])
    return "\n".join(lines)


def agent_prompt(
    arm: str,
    question: dict[str, Any],
    config: dict[str, Any],
    source: dict[str, Any],
) -> str:
    context = design_context(config, source)
    common = (
        "Work carefully until you have the strongest evidence available. "
        "Do not use the network. End with exactly one final line in the form "
        "ANSWER: <concise answer>.\n\n"
    )
    if arm == "source":
        role = (
            "You are the source-analysis arm of a controlled hardware-design "
            "benchmark. You have the complete, exact configuration below. "
            "Use any useful read-only local analysis: rg/grep, file reads, "
            "find, git, awk/sed, shell pipelines, and read-only scripts or "
            "one-liners. Follow the configured file list, includes, defines, "
            "packages, generate conditions, and parameter flow. You may inspect "
            "a generated artifact only when its metadata proves that it was "
            "built from this exact revision and configuration. Do not use "
            "naja-scope, another netlist database, an HDL elaborator, synthesis, "
            "or simulation. If source text cannot establish a post-elaboration "
            "fact, explain that limitation instead of guessing.\n\n"
        )
    elif arm == "scope":
        role = (
            "You are the naja-scope arm of a controlled hardware-design "
            "benchmark. Query only the naja-scope MCP tools. The design is "
            "already loaded with the exact configuration below. Do not use "
            "shell commands, direct file reads, repository search, other MCP "
            "servers, or the network. Use get_source only for the bounded source "
            "excerpt associated with a resolved design object.\n\n"
        )
    else:
        raise ValueError(f"unknown arm: {arm}")
    return (
        role + common + "EXACT DESIGN CONTEXT\n" + context +
        "\n\nQUESTION\n" + question["question"].strip())


def extract_answer(text: str) -> str | None:
    """Return the last ANSWER block, including multiline continuations.

    The old harness kept only the first line, creating a false negative when an
    agent put a code block after ``ANSWER:``.  Missing markers are review items,
    not automatic failures.
    """
    matches = list(re.finditer(r"(?im)^\s*ANSWER:\s*", text or ""))
    if not matches:
        return None
    return (text or "")[matches[-1].end():].strip()


def score_answer(text: str, check: dict[str, Any]) -> tuple[str, str]:
    answer = extract_answer(text)
    if answer is None:
        return "review", "missing final ANSWER marker"
    normalized = re.sub(r"\s+", " ", answer.lower()).strip()
    ctype = check.get("type")
    if ctype == "contains_all":
        ok = all(str(term).lower() in normalized for term in check["terms"])
    elif ctype == "any_of":
        ok = any(all(str(term).lower() in normalized for term in group)
                 for group in check["groups"])
    elif ctype == "regex_all":
        ok = all(re.search(pattern, answer, re.I | re.S)
                 for pattern in check["patterns"])
    elif ctype == "primary_numeric":
        numbers = re.findall(r"(?<![A-Za-z_])-?\d[\d,]*(?:\.\d+)?", answer)
        if not numbers:
            return "review", "no numeric value in final answer"
        expected = float(check["value"])
        actual = float(numbers[0].replace(",", ""))
        ok = abs(actual - expected) <= float(check.get("tol", 0))
    else:
        raise ValueError(f"unknown check type: {ctype!r}")
    if ok:
        for pattern in check.get("reject_patterns", []):
            if re.search(pattern, answer, re.I | re.S):
                return "fail", f"matched rejection pattern: {pattern}"
        return "pass", "deterministic check passed"
    return "fail", "deterministic check failed"


def _claude_command(
    binary: str,
    spec: AgentSpec,
    arm: str,
    prompt: str,
    cwd: Path,
    source_root: Path,
    mcp_config: Path | None,
    max_turns: int,
    effort: str,
) -> list[str]:
    cmd = [
        binary, "-p", prompt, "--model", spec.model, "--effort", effort,
        "--output-format", "stream-json", "--verbose",
        "--no-session-persistence", "--restricted", "--disable-slash-commands",
        "--permission-mode", "dontAsk", "--max-turns", str(max_turns),
    ]
    if arm == "source":
        cmd += ["--strict-mcp-config", "--tools", "Bash,Read,Grep,Glob",
                "--add-dir", str(source_root)]
    else:
        if mcp_config is None:
            raise ValueError("scope arm requires an MCP config")
        cmd += [
            "--strict-mcp-config", "--mcp-config", str(mcp_config),
            "--tools", CLAUDE_SCOPE_ALLOWED,
            "--allowedTools", CLAUDE_SCOPE_ALLOWED,
            "--disallowedTools", CLAUDE_SCOPE_DENIED,
        ]
    return cmd


def _toml_string(value: str) -> str:
    return json.dumps(value)


def _codex_command(
    binary: str,
    spec: AgentSpec,
    arm: str,
    prompt: str,
    cwd: Path,
    source_root: Path,
    mcp_url: str | None,
    effort: str,
    last_message: Path,
) -> list[str]:
    agent_cwd = source_root if arm == "source" else cwd
    cmd = [
        binary, "exec", "--json", "--ephemeral", "--ignore-user-config",
        "--ignore-rules", "--skip-git-repo-check", "--model", spec.model,
        "--sandbox", "read-only", "--cd", str(agent_cwd),
        "--output-last-message", str(last_message),
        "-c", f"model_reasoning_effort={_toml_string(effort)}",
    ]
    if arm == "scope":
        if not mcp_url:
            raise ValueError("scope arm requires an MCP URL")
        cmd += ["-c", f"mcp_servers.naja_scope.url={_toml_string(mcp_url)}"]
    cmd.append(prompt)
    return cmd


def build_command(
    spec: AgentSpec,
    arm: str,
    prompt: str,
    cwd: Path,
    source_root: Path,
    mcp_url: str | None,
    mcp_config: Path | None,
    max_turns: int,
    effort: str,
    last_message: Path,
) -> list[str]:
    binary = shutil.which("claude" if spec.provider == "anthropic" else "codex")
    if not binary:
        raise FileNotFoundError(f"{spec.provider} CLI is not installed")
    if spec.provider == "anthropic":
        return _claude_command(binary, spec, arm, prompt, cwd, source_root,
                               mcp_config, max_turns, effort)
    return _codex_command(binary, spec, arm, prompt, cwd, source_root,
                          mcp_url, effort, last_message)


def _json_lines(text: str) -> list[dict[str, Any]]:
    events = []
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def _usage_from_claude(events: list[dict[str, Any]]) -> dict[str, Any]:
    result = next((event for event in reversed(events)
                   if event.get("type") == "result"), {})
    models = result.get("modelUsage") or {}
    if models:
        input_tokens = sum(
            (item.get("inputTokens") or 0) +
            (item.get("cacheReadInputTokens") or 0) +
            (item.get("cacheCreationInputTokens") or 0)
            for item in models.values())
        output_tokens = sum((item.get("outputTokens") or 0)
                            for item in models.values())
    else:
        usage = result.get("usage") or {}
        input_tokens = sum(usage.get(key) or 0 for key in (
            "input_tokens", "cache_read_input_tokens",
            "cache_creation_input_tokens"))
        output_tokens = usage.get("output_tokens") or 0
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "turns": result.get("num_turns"),
        "cost_usd": result.get("total_cost_usd"),
        "terminal_reason": result.get("terminal_reason") or result.get("subtype"),
        "model_usage": models,
        "result_text": result.get("result") or "",
    }


def _walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_dicts(item)


def _usage_from_codex(events: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = []
    for event in events:
        for item in _walk_dicts(event):
            if "input_tokens" in item and "output_tokens" in item:
                candidates.append(item)
    usage = max(candidates,
                key=lambda item: (item.get("input_tokens") or 0) +
                                 (item.get("output_tokens") or 0),
                default={})
    return {
        # OpenAI input_tokens already includes cached input; cached_input_tokens
        # is a subset and must not be added again.
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cached_input_tokens": usage.get("cached_input_tokens"),
        "reasoning_output_tokens": usage.get("reasoning_output_tokens"),
        "turns": None,
        "cost_usd": None,
        "terminal_reason": events[-1].get("type") if events else None,
    }


def trace_tool_names(provider: str, events: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for event in events:
        for item in _walk_dicts(event):
            if item.get("type") == "tool_use" and item.get("name"):
                names.append(str(item["name"]))
            item_type = str(item.get("type", ""))
            if item_type in {"command_execution", "CommandExecution"}:
                names.append("shell")
            elif "mcp" in item_type.lower():
                names.append(str(item.get("tool") or item.get("name") or item_type))
    return names


def compliance_warnings(arm: str, tool_names: list[str]) -> list[str]:
    warnings = []
    for name in tool_names:
        lowered = name.lower()
        if arm == "source" and "mcp" in lowered:
            warnings.append(f"source arm used MCP tool {name}")
        if arm == "scope" and (name == "shell" or lowered in {
                "bash", "read", "grep", "glob", "webfetch", "websearch"}):
            warnings.append(f"scope arm used forbidden tool {name}")
    return sorted(set(warnings))


def cli_version(spec: AgentSpec) -> str | None:
    binary = shutil.which("claude" if spec.provider == "anthropic" else "codex")
    if not binary:
        return None
    proc = subprocess.run([binary, "--version"], capture_output=True, text=True)
    return (proc.stdout or proc.stderr).strip() or None


def package_version(name: str) -> str | None:
    try:
        return importlib_metadata.version(name)
    except importlib_metadata.PackageNotFoundError:
        return None


def run_one(
    spec: AgentSpec,
    arm: str,
    question: dict[str, Any],
    repetition: int,
    config: dict[str, Any],
    source: dict[str, Any],
    source_root: Path,
    outdir: Path,
    mcp_url: str | None,
    mcp_config: Path | None,
    max_turns: int,
    timeout: int,
    effort: str,
) -> dict[str, Any]:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_",
                  f"{spec.provider}_{spec.model}_{question['id']}_{arm}_r{repetition}")
    trace_path = outdir / f"{stem}.trace.jsonl"
    answer_path = outdir / f"{stem}.answer.txt"
    stderr_path = outdir / f"{stem}.stderr.txt"
    with tempfile.TemporaryDirectory(prefix="naja-scope-bench-") as scratch:
        cwd = Path(scratch)
        prompt = agent_prompt(arm, question, config, source)
        command = build_command(
            spec, arm, prompt, cwd, source_root, mcp_url, mcp_config,
            max_turns, effort, answer_path)
        env = os.environ.copy()
        env.update({str(key): str(value)
                    for key, value in config.get("environment", {}).items()})
        started = time.monotonic()
        try:
            agent_cwd = source_root if arm == "source" else cwd
            proc = subprocess.run(
                command, cwd=agent_cwd, env=env, capture_output=True, text=True,
                timeout=timeout)
            stdout, stderr, timed_out = proc.stdout, proc.stderr, False
            returncode = proc.returncode
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            timed_out, returncode = True, None
        wall_seconds = round(time.monotonic() - started, 3)
    trace_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    events = _json_lines(stdout)
    if spec.provider == "anthropic":
        usage = _usage_from_claude(events)
        answer = usage.pop("result_text")
        answer_path.write_text(answer, encoding="utf-8")
    else:
        usage = _usage_from_codex(events)
        answer = answer_path.read_text(encoding="utf-8") if answer_path.exists() else ""
    tools = trace_tool_names(spec.provider, events)
    score, score_reason = score_answer(answer, question["check"])
    warnings = compliance_warnings(arm, tools)
    if timed_out:
        score, score_reason = "invalid", "agent process timed out"
    elif returncode != 0:
        score, score_reason = "invalid", f"agent process exited {returncode}"
    elif warnings:
        score, score_reason = "invalid", "; ".join(warnings)
    return {
        "provider": spec.provider,
        "model": spec.model,
        "arm": arm,
        "question_id": question["id"],
        "category": question.get("category"),
        "repetition": repetition,
        "score": score,
        "score_reason": score_reason,
        "answer": answer,
        "usage": usage,
        "tool_calls": len(tools),
        "tools": tools,
        "compliance_warnings": warnings,
        "wall_seconds": wall_seconds,
        "timed_out": timed_out,
        "returncode": returncode,
        "stderr_tail": stderr[-2000:],
        "trace": trace_path.name,
        "answer_file": answer_path.name,
        "stderr_file": stderr_path.name,
    }


class WarmServer:
    def __init__(self, config_path: Path, source_root: Path, outdir: Path,
                 host: str, port: int, timeout: int):
        self.ready = outdir / "server-ready.json"
        self.log = outdir / "server.log"
        self.host, self.port, self.timeout = host, port, timeout
        self.command = [
            sys.executable, str(HERE / "serve_design.py"),
            "--config", str(config_path), "--source-root", str(source_root),
            "--host", host, "--port", str(port),
            "--ready-file", str(self.ready),
        ]
        self.process: subprocess.Popen[str] | None = None
        self._log_handle = None

    def start(self) -> dict[str, Any]:
        try:
            with socket.create_server((self.host, self.port)):
                pass
        except OSError as exc:
            raise RuntimeError(
                f"cannot reserve warm-server address {self.host}:{self.port}: "
                f"{exc}") from exc
        self._log_handle = self.log.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            self.command, stdout=self._log_handle, stderr=subprocess.STDOUT,
            text=True)
        started = time.monotonic()
        ready: dict[str, Any] | None = None
        while time.monotonic() - started < self.timeout:
            if self.process.poll() is not None:
                raise RuntimeError(f"warm server exited; see {self.log}")
            if self.ready.exists():
                try:
                    ready = json.loads(self.ready.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    pass
            if ready:
                try:
                    with socket.create_connection(
                            (self.host, self.port), timeout=0.5):
                        return ready
                except OSError:
                    pass
            time.sleep(0.5)
        self.stop()
        raise TimeoutError(f"warm server not ready after {self.timeout}s")

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if self._log_handle:
            self._log_handle.close()


def write_summary(outdir: Path, metadata: dict[str, Any],
                  results: list[dict[str, Any]]) -> None:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for result in results:
        key = (result["provider"], result["model"], result["arm"])
        groups.setdefault(key, []).append(result)
    lines = [
        f"# Agent comparison: {metadata['design']['label']}", "",
        f"Configuration fingerprint: `{metadata['fingerprint']}`", "",
        "| Provider | Requested model | Models observed | CLI | Effort | Arm | "
        "Runs | Pass | Fail | Review/invalid | Input tokens | Output tokens | "
        "Tool calls | Wall s |",
        "|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    versions = metadata["agents"]
    for (provider, model, arm), rows in sorted(groups.items()):
        count = lambda status: sum(row["score"] == status for row in rows)
        observed = sorted({
            observed_model
            for row in rows
            for observed_model in (row["usage"].get("model_usage") or {model})
        })
        input_tokens = sum((row["usage"].get("input_tokens") or 0) for row in rows)
        output_tokens = sum((row["usage"].get("output_tokens") or 0) for row in rows)
        lines.append(
            f"| {provider} | `{model}` | {', '.join(f'`{item}`' for item in observed)} | "
            f"{versions[f'{provider}:{model}'] or 'missing'} | {metadata['effort']} | "
            f"{arm} | {len(rows)} | {count('pass')} | {count('fail')} | "
            f"{count('review') + count('invalid')} | {input_tokens} | "
            f"{output_tokens} | {sum(row['tool_calls'] for row in rows)} | "
            f"{sum(row['wall_seconds'] for row in rows):.1f} |")
    (outdir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (outdir / "summary.json").write_text(
        json.dumps({"metadata": metadata, "results": results}, indent=2),
        encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--agent", type=parse_agent_spec, action="append", required=True,
                        help="repeatable PROVIDER:MODEL entry")
    parser.add_argument("--arm", choices=("both", "scope", "source"), default="both")
    parser.add_argument("--ids", nargs="*")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--effort", choices=("low", "medium", "high", "xhigh"),
                        default="high")
    parser.add_argument("--max-turns", type=int, default=24,
                        help="Claude Code limit; Codex is bounded by timeout")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--server-ready-timeout", type=int, default=4500)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--out", type=Path, default=REPO / "benchmark-results")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.repetitions < 1:
        parser.error("--repetitions must be positive")
    source_root = args.source_root.resolve()
    if not source_root.is_dir():
        parser.error(f"source root does not exist: {source_root}")
    config_path = args.config.resolve()
    config = load_config(config_path, source_root)
    flist = Path(config["load"]["flist"])
    if not flist.is_file():
        parser.error(f"configured file list does not exist: {flist}")
    source = git_metadata(source_root)
    expected = config.get("expected_revision")
    if expected and source["revision"] != expected:
        parser.error(
            f"source revision {source['revision']} != expected {expected}")
    if source["dirty"] and not args.allow_dirty:
        parser.error(
            f"source tree has {source['dirty_paths']} changed path(s); use a "
            "clean checkout or pass --allow-dirty (recorded in metadata)")
    agent_keys = [spec.key for spec in args.agent]
    if len(agent_keys) != len(set(agent_keys)):
        parser.error("duplicate --agent entries are not allowed")

    questions = config["questions"]
    if args.ids:
        selected = set(args.ids)
        known = {q["id"] for q in questions}
        unknown = sorted(selected - known)
        if unknown:
            parser.error(f"unknown question id(s): {', '.join(unknown)}")
        questions = [q for q in questions if q["id"] in selected]
    if not questions:
        parser.error("no questions selected")
    for question in questions:
        status, reason = score_answer(
            "ANSWER: " + question["golden"], question["check"])
        if status != "pass":
            parser.error(f"golden self-check failed for {question['id']}: {reason}")

    arms = ["scope", "source"] if args.arm == "both" else [args.arm]
    fingerprint = config_fingerprint(config, source)
    versions = {spec.key: cli_version(spec) for spec in args.agent}
    metadata = {
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "fingerprint": fingerprint,
        "design": config,
        "source": source,
        "agents": versions,
        "agent_executables": {
            spec.key: shutil.which(
                "claude" if spec.provider == "anthropic" else "codex")
            for spec in args.agent
        },
        "harness_source": git_metadata(REPO),
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
            "naja-scope": package_version("naja-scope"),
            "najaeda": package_version("najaeda"),
            "mcp": package_version("mcp"),
        },
        "repetitions": args.repetitions,
        "seed": args.seed,
        "effort": args.effort,
        "max_turns_anthropic": args.max_turns,
        "timeout_seconds": args.timeout_seconds,
        "suite_kind": config.get("suite_kind", "unspecified"),
    }

    # Keep the two arms for one model/question adjacent to minimize temporal
    # drift, but randomize both block order and which arm goes first.
    rng = random.Random(args.seed)
    blocks = [(spec, question, repetition)
              for repetition in range(1, args.repetitions + 1)
              for question in questions
              for spec in args.agent]
    rng.shuffle(blocks)
    tasks = []
    for spec, question, repetition in blocks:
        block_arms = list(arms)
        rng.shuffle(block_arms)
        tasks.extend((spec, arm, question, repetition) for arm in block_arms)

    if args.dry_run:
        print(json.dumps(metadata, indent=2))
        print(f"\nMatrix: {len(tasks)} runs ({len(questions)} questions)")
        for spec, arm, question, repetition in tasks:
            print(f"  {spec.key} {arm} {question['id']} r{repetition}")
        with tempfile.TemporaryDirectory(prefix="naja-scope-bench-dry-") as scratch:
            scratch_path = Path(scratch)
            mcp_url = "http://127.0.0.1:8765/mcp"
            mcp_path = scratch_path / "mcp.json"
            mcp_path.write_text(json.dumps({"mcpServers": {"naja-scope": {
                "type": "http", "url": mcp_url}}}), encoding="utf-8")
            print("\nCommand adapters:")
            for spec in args.agent:
                for arm in arms:
                    question = questions[0]
                    prompt = agent_prompt(arm, question, config, source)
                    command = build_command(
                        spec, arm, prompt, scratch_path, source_root, mcp_url,
                        mcp_path, args.max_turns, args.effort,
                        scratch_path / "answer.txt")
                    # Do not print the large embedded prompt.
                    printable = ["<PROMPT>" if item == prompt else item
                                 for item in command]
                    print(f"  {spec.key} {arm}: {shlex.join(printable)}")
        return 0

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = args.out.resolve() / f"{config['id']}_{stamp}_{fingerprint}"
    outdir.mkdir(parents=True)
    (outdir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8")

    server = None
    mcp_url = None
    mcp_config = outdir / "mcp.json"
    try:
        if "scope" in arms:
            server = WarmServer(
                config_path, source_root, outdir, args.host, args.port,
                args.server_ready_timeout)
            ready = server.start()
            if ready.get("fingerprint") != fingerprint:
                raise RuntimeError(
                    "warm-server configuration fingerprint does not match runner")
            mcp_url = ready["url"]
            metadata["warm_server"] = ready
            (outdir / "metadata.json").write_text(
                json.dumps(metadata, indent=2), encoding="utf-8")
        if "scope" in arms:
            mcp_config.write_text(json.dumps({"mcpServers": {"naja-scope": {
                "type": "http", "url": mcp_url}}}, indent=2), encoding="utf-8")
        results = []
        for spec, arm, question, repetition in tasks:
            print(f"[run] {spec.key} {arm} {question['id']} r{repetition}",
                  file=sys.stderr)
            result = run_one(
                spec, arm, question, repetition, config, source, source_root,
                outdir, mcp_url, mcp_config, args.max_turns,
                args.timeout_seconds, args.effort)
            results.append(result)
            result_path = outdir / (Path(result["trace"]).stem + ".result.json")
            result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
            write_summary(outdir, metadata, results)
    finally:
        if server:
            server.stop()
    print(f"Results: {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
