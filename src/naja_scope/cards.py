# SPDX-License-Identifier: Apache-2.0
"""Deterministic module cards: ~200-token orientation summaries built from
structure only — no LLM at indexing time (DESIGN.md section 7)."""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from . import snl
from .errors import ScopeError
from .session import Session

_CLK_RE = re.compile(r"(?:^|_)(clk|clock|ck)(?:$|_|\d)", re.IGNORECASE)
_RST_RE = re.compile(r"(?:^|_)(rst|reset)(?:$|_|\d|n\b)", re.IGNORECASE)
_ACTIVE_LOW_RE = re.compile(r"(_n|_b|_l|n)$", re.IGNORECASE)

_DIR_NAMES = {0: "input", 1: "output", 2: "inout"}


def _dir_str(direction) -> str:
    s = str(direction)
    if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
        return _DIR_NAMES.get(int(s), s)
    return s.split(".")[-1].lower()


def find_design(name: str):
    design = snl.find_design(name)
    if design is not None:
        return design
    raise ScopeError(f"No module named '{name}'.", snl.suggest_designs(name))


def _ports(design) -> List[dict]:
    ports = []
    for bus in design.getBusTerms():
        ports.append({
            "name": bus.getName(),
            "dir": _dir_str(bus.getDirection()),
            "msb": bus.getMSB(),
            "lsb": bus.getLSB(),
            "width": abs(bus.getMSB() - bus.getLSB()) + 1,
        })
    for bit in design.getBitTerms():
        if type(bit).__name__ == "SNLBusTermBit":
            continue
        ports.append({
            "name": bit.getName(),
            "dir": _dir_str(bit.getDirection()),
            "width": 1,
        })
    return ports


def _model_is_sequential(model) -> bool:
    try:
        return bool(model.isSequential())
    except Exception:
        return False


def module_card(session: Session, module: str,
                max_models: int = 12) -> dict:
    session.require_top()
    design = find_design(module)
    ports = _ports(design)

    by_model: Dict[str, int] = {}
    total = 0
    sequential = 0
    for inst in design.getInstances():
        total += 1
        model = inst.getModel()
        model_name = model.getName()
        by_model[model_name] = by_model.get(model_name, 0) + 1
        if _model_is_sequential(model):
            sequential += 1

    top_models = sorted(by_model.items(), key=lambda kv: -kv[1])
    counts = {
        "instances": total,
        "sequential_instances": sequential,
        "models": len(by_model),
        "by_model": dict(top_models[:max_models]),
    }
    if len(top_models) > max_models:
        counts["by_model_truncated"] = True

    inputs = [p for p in ports if p["dir"] == "input"]
    clocks = [p["name"] for p in inputs if _CLK_RE.search(p["name"])]
    resets = [{
        "name": p["name"],
        "active_low_guess": bool(_ACTIVE_LOW_RE.search(p["name"])),
    } for p in inputs if _RST_RE.search(p["name"])]

    params = []
    try:
        for p in design.getParameters():
            params.append({"name": p.getName(), "value": p.getValue()})
    except Exception:
        pass

    card = {
        "module": module,
        "ports": ports,
        "counts": counts,
        "clock_candidates": clocks,
        "reset_candidates": resets,
        "heuristic_fields": ["clock_candidates", "reset_candidates"],
    }
    if params:
        card["parameters"] = params

    index = _safe_index(session)
    if index is not None:
        rng = index.module_range(module)
        if rng:
            card["src"] = rng.to_ref()
    return card


def _safe_index(session: Session) -> Optional[object]:
    try:
        return session.get_source_index()
    except Exception:
        return None
