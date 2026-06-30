# SPDX-License-Identifier: Apache-2.0
"""Deterministic module cards.

A *card* is a small, fixed-size, deterministic summary of one elaborated
module -- like an index card or a baseball card: a compact at-a-glance profile,
not the full record. It is a naja-scope concept (the `get_module_card` tool),
not a najaeda/SNL one.

Why it exists: naja-scope lets an agent navigate a design *without* dumping
source into its context window. When an agent first meets a module it needs
orientation -- what is this, how big is it, what are its ports -- so a card
answers that in ~200 tokens, letting the agent decide where to look next
instead of reading the RTL.

Defining properties:
  - Structure-only: built purely from the elaborated netlist (SNL) -- ports,
    instance/model counts, parameters, source range. No source text is read
    into context.
  - No LLM at indexing time: cards are computed deterministically, never
    generated. LLM summaries cost scales with design size, go stale on every
    edit, and a hallucination silently poisons the agent's reasoning; the
    querying agent is already a frontier model, so give it facts.
  - Token-bounded: lists are capped and counted (e.g. `by_model` truncates at
    `max_models` and sets `by_model_truncated`).

The structural fields are hard facts. The clock/reset fields are name-based
guesses -- see the WORKAROUND note below -- and the card self-labels them
(`heuristic_fields`, `name_based_workaround`) so consumers know which of its
own fields to trust.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from . import snl
from .errors import ScopeError
from .session import Session
from .source_index import SrcRange

# --- WORKAROUND: name-based clock/reset identification -----------------------
# Identifying clocks, resets, and reset polarity by *port name* is fundamentally
# unsound: names are conventions, not semantics, and any of these guesses can be
# wrong. This is a stopgap until structural detection lands:
#   - clocks: from SDC (`create_clock` ...) constraints, and by back-propagating
#     from the clock pins of sequential cells (flip-flops/latches);
#   - resets / polarity: by back-propagating from the (a)synchronous reset pins
#     of sequential cells and reading the pin's active level,
# never from the signal name. Until naja exposes FF clock/reset pin roles (and
# we ingest SDC), these fields stay name-based and are flagged as a workaround
# in the card output (`name_based_workaround`). Do not build anything on top of
# them that assumes they are reliable.
_CLK_RE = re.compile(r"(?:^|_)(clk|clock|ck)(?:$|_|\d)", re.IGNORECASE)
_RST_RE = re.compile(r"(?:^|_)(rst|reset)(?:$|_|\d|n\b)", re.IGNORECASE)
# Active-low polarity guess: strip a trailing input/output direction suffix
# first so the lowRISC/CVA6 convention `rst_ni` / `arst_ni` reads as `rst_n`
# rather than ending in the `i` direction marker, then look for an active-low
# marker. The marker is `_i`/`_o` on a plain name (`clk_i`) but a bare `i`/`o`
# once an active-low `_n` is already present (`rst_n` + `i` -> `rst_ni`), so the
# underscore is optional.
_DIR_SUFFIX_RE = re.compile(r"_?[io]$", re.IGNORECASE)
_ACTIVE_LOW_RE = re.compile(r"(_n|_b|_l|rstn|resetn)$", re.IGNORECASE)

_DIR_NAMES = {0: "input", 1: "output", 2: "inout"}


def _active_low_guess(name: str) -> bool:
    """Name-based active-low reset guess (WORKAROUND — see module note)."""
    base = _DIR_SUFFIX_RE.sub("", name)
    return bool(_ACTIVE_LOW_RE.search(base))


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
    """Build the orientation card for `module` (see module docstring).

    Returns a dict with:
      - `module`: the module name.
      - `ports`: per-port name/dir/width (msb/lsb for buses). Hard fact.
      - `counts`: instances, sequential_instances, models, and `by_model`
        (top `max_models` by count, with `by_model_truncated` if elided). Hard
        fact.
      - `parameters`: name/value pairs, when present. Hard fact.
      - `src`: the module's source range as `file:start-end`, when known.
      - `clock_candidates` / `reset_candidates` (+ `active_low_guess`):
        name-based GUESSES, not facts -- see the WORKAROUND note above.
      - `heuristic_fields` / `name_based_workaround`: lists naming which fields
        above are heuristic, so a consumer knows which to trust.
    """
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
        "active_low_guess": _active_low_guess(p["name"]),
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
        # WORKAROUND: clock/reset fields are guessed from port names, which is
        # unsound. The sound source is SDC (create_clock) + back-propagation
        # from sequential-cell clock/reset pins.
        "name_based_workaround": ["clock_candidates", "reset_candidates"],
    }
    if params:
        card["parameters"] = params

    loc = snl.source_loc(design)
    if loc:
        card["src"] = SrcRange.from_loc(loc).to_ref()
    return card
