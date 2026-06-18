# SPDX-License-Identifier: Apache-2.0
"""Correctness scoring for eval answers.

Each question carries a `check` spec. Deterministic checks (the common case for
structural questions) need no LLM and are reproducible; open-ended questions
fall back to an LLM judge (invoked by run_eval, not here).

Agents are instructed to end their reply with a line `ANSWER: ...`; we score
that line if present, else the whole text.

check spec forms (YAML):
  {type: contains_all, terms: [a, b]}        all terms present (normalized)
  {type: any_of, groups: [[a,b],[c]]}        any group fully present
  {type: regex, pattern: '...'}              re.search on raw answer
  {type: numeric, value: 40, tol: 0}         a number == value (±tol) appears
  {type: judge, rubric: '...'}               defer to LLM judge (run_eval)
"""
from __future__ import annotations

import re
from typing import Optional


def extract_answer(text: str) -> str:
    if not text:
        return ""
    m = re.findall(r"(?im)^\s*ANSWER:\s*(.+)$", text)
    return m[-1].strip() if m else text.strip()


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def needs_judge(check: dict) -> bool:
    return (check or {}).get("type") == "judge"


def score(answer_text: str, check: dict) -> Optional[bool]:
    """Return True/False for deterministic checks, or None if the check defers
    to the LLM judge."""
    ctype = (check or {}).get("type")
    ans = extract_answer(answer_text)
    norm = _norm(ans)

    if ctype == "contains_all":
        return all(_norm(t) in norm for t in check["terms"])
    if ctype == "any_of":
        return any(all(_norm(t) in norm for t in group)
                   for group in check["groups"])
    if ctype == "regex":
        return re.search(check["pattern"], ans) is not None
    if ctype == "numeric":
        tol = check.get("tol", 0)
        target = float(check["value"])
        for tok in re.findall(r"-?\d[\d,]*\.?\d*", ans.replace(",", "")):
            try:
                if abs(float(tok) - target) <= tol:
                    return True
            except ValueError:
                continue
        return False
    if ctype == "judge":
        return None
    raise ValueError(f"Unknown check type: {ctype!r}")


# Rubric handed to the LLM judge for `type: judge` questions.
JUDGE_PROMPT = """You are grading an answer to a hardware-design question about \
a SystemVerilog netlist. Compare the CANDIDATE answer to the GOLDEN answer.

QUESTION: {question}
GOLDEN: {golden}
RUBRIC: {rubric}
CANDIDATE: {candidate}

Reply with exactly one word on the first line: CORRECT, PARTIAL, or INCORRECT."""
