# SPDX-License-Identifier: Apache-2.0
"""Cone tracing on top of naja's native `LogicCone`.

`LogicCone(seed_occurrence, FanIn|FanOut)` builds, in C++, the rooted DAG
of combinational logic between the seed bit and the surrounding sequential /
port / black-box barriers, crossing hierarchy and following combinatorial arcs
only. naja-scope no longer hand-rolls the equipotential BFS; it seeds the cone,
then turns the DAG into a token-bounded summary:

* `get_node_count()` / `get_nodes()` kinds  -> size + counts_by_kind,
* `get_leaves()`                            -> the stop-at-flops frontier
  (flops, top ports, opaque black boxes), categorised and bounded,
* the flop frontier grouped by top-level submodule, naming the registers that
  lie OUTSIDE the cone root's own subtree -> the cross-hierarchy answer.

Token-bounding here is a correctness requirement: counts
are always exact, but every materialised list is capped with a truncation
marker — never a full node/edge dump.

The native cone is intrinsically stop-at-flops (a flop's D->Q is not a
combinatorial arc), so there is no `stop=none` mode and no traversal cap; size
bounding is the caller's job and lives here.
"""

from __future__ import annotations

from typing import Dict, List

from najaeda import naja

from . import snl
from .errors import ScopeError
from .resolve import Resolved
from .source_index import SrcRange

DEFAULT_MAX_FRONTIER = 50
HARD_MAX_FRONTIER = 200

_DIRECTIONS = {
    "fanin": naja.LogicCone.FanIn,
    "fanout": naja.LogicCone.FanOut,
}
# get_leaves() kinds that are barriers, by category.
_LEAF_KINDS = {"flop", "ports", "blackbox"}


def _bits_of(resolved: Resolved) -> List:
    if resolved.kind in ("term", "net"):
        return snl.obj_bits(resolved.obj)
    raise ScopeError(f"'{resolved.path}' is an instance; trace_cone expects a "
                     "term or net.")


def _subtree_key(path: str) -> str:
    """Top-level submodule a hierarchical path lives in: `top.<submodule>`.

    `cva6.ex_stage_i.i_mult.i_div.state_q` -> `cva6.ex_stage_i`. A path sitting
    directly under the top (`cva6.some_reg`) yields just the top name.
    """
    segs = path.split(".")
    return ".".join(segs[:2]) if len(segs) >= 3 else segs[0]


def _port_label(netcomp) -> str:
    top = snl.top_design().getName()
    name = netcomp.getName()
    bit = None
    if type(netcomp).__name__ == "SNLBusTermBit":
        try:
            bit = netcomp.getBit()
        except Exception:
            bit = None
    return f"{top}.{name}" + (f"[{bit}]" if bit is not None else "")


def _leaf_record(inst, ids) -> dict:
    entry = {"path": snl.path_str_from_ids(ids),
             "label": snl.friendly_label(inst),
             "model": inst.getModel().getName()}
    loc = snl.source_loc(inst)
    if loc:
        entry["src"] = SrcRange.from_loc(loc).to_ref()
    return entry


def _display_path(rec: dict) -> str:
    """A readable path for a frontier record: its hierarchical path with the
    trailing anonymous `#id` segment replaced by the driven-net label
    (`cva6.csr_regfile_i.priv_lvl_q_dffrn`). Falls back to the raw path."""
    head, _, tail = rec["path"].rpartition(".")
    label = rec.get("label")
    if head and tail.startswith("#") and label:
        return f"{head}.{label}"
    return rec["path"]


def _cross_hierarchy(root_path: str, flops: Dict[str, dict]) -> dict:
    """Group the flop frontier by top-level submodule and name the registers
    outside the cone root's own subtree — the cross-hierarchy affordance: in one
    call the agent learns whether (and where) the cone reaches register state
    outside `<stage>`. Token-bounded: per-subtree counts plus a few example
    paths, never a dump."""
    root_subtree = _subtree_key(root_path)
    by_subtree: Dict[str, dict] = {}
    for path, rec in flops.items():
        key = _subtree_key(path)
        bucket = by_subtree.setdefault(key, {"count": 0, "examples": []})
        bucket["count"] += 1
        if len(bucket["examples"]) < 3:
            # Show the readable label for the register, not its `#id` segment,
            # so the agent learns *which* registers the cone reaches.
            bucket["examples"].append(_display_path(rec))

    outside = {k: v for k, v in by_subtree.items() if k != root_subtree}
    outside_examples: List[str] = []
    for v in outside.values():
        outside_examples.extend(v["examples"])

    return {
        "root_subtree": root_subtree,
        "by_subtree": dict(
            sorted(by_subtree.items(), key=lambda kv: -kv[1]["count"])[:20]),
        "outside_root_subtree": {
            "count": sum(v["count"] for v in outside.values()),
            "subtrees": sorted(outside.keys()),
            "examples": outside_examples[:10],
        },
    }


def trace_cone(resolved: Resolved, session, direction: str,
               max_frontier: int = DEFAULT_MAX_FRONTIER) -> dict:
    if direction not in _DIRECTIONS:
        raise ScopeError("direction must be 'fanin' or 'fanout'.")
    max_frontier = max(1, min(max_frontier, HARD_MAX_FRONTIER))
    cone_dir = _DIRECTIONS[direction]

    bits = _bits_of(resolved)
    node_count = 0
    counts_by_kind: Dict[str, int] = {}
    counts_by_model: Dict[str, int] = {}
    # Frontier deduped across seed bits by identity (path / port label).
    flops: Dict[str, dict] = {}
    blackboxes: Dict[str, dict] = {}
    ports: Dict[str, dict] = {}

    for bit in bits:
        occ = snl.seed_occurrence(resolved.kind, resolved.owner, bit)
        if occ is None:
            continue
        cone = naja.LogicCone(occ, cone_dir)
        node_count += cone.get_node_count()
        for (_id, _occ, kind, _nx, _pv) in cone.get_nodes():
            counts_by_kind[kind] = counts_by_kind.get(kind, 0) + 1
        for (_id, leaf_occ, kind, _nx, _pv) in cone.get_leaves():
            if kind == "ports":
                nc = leaf_occ.getNetComponent()
                if nc is None:
                    continue
                label = _port_label(nc)
                ports.setdefault(label, {"port": label})
                continue
            inst, ids = snl.occurrence_leaf(leaf_occ)
            if inst is None:
                continue
            rec = _leaf_record(inst, ids)
            if kind == "flop":
                if rec["path"] not in flops:
                    flops[rec["path"]] = rec
                    counts_by_model[rec["model"]] = (
                        counts_by_model.get(rec["model"], 0) + 1)
            else:  # blackbox (opaque leaf cell) or any other un-crossed leaf
                blackboxes.setdefault(rec["path"], rec)

    flop_list = sorted(flops.values(), key=lambda r: r["path"])
    bb_list = sorted(blackboxes.values(), key=lambda r: r["path"])
    port_list = sorted(ports.values(), key=lambda r: r["port"])
    frontier_truncated = (len(flop_list) > max_frontier
                          or len(bb_list) > max_frontier
                          or len(port_list) > max_frontier)

    out = {
        "root": resolved.path,
        "direction": direction,
        "stop": "flops",  # native cone always stops at flops/ports/black boxes
        "seed_bits": len(bits),
        "node_count": node_count,
        "node_count_summed_over_bits": len(bits) > 1,
        "counts_by_kind": dict(
            sorted(counts_by_kind.items(), key=lambda kv: -kv[1])),
        "frontier": {
            "flop_count": len(flop_list),
            "port_count": len(port_list),
            "blackbox_count": len(bb_list),
            "flops": flop_list[:max_frontier],
            "ports": port_list[:max_frontier],
            "blackboxes": bb_list[:max_frontier],
            "truncated": frontier_truncated,
        },
        "counts_by_model": dict(
            sorted(counts_by_model.items(), key=lambda kv: -kv[1])[:20]),
        "cross_hierarchy": _cross_hierarchy(resolved.path, flops),
        "truncated": frontier_truncated,
    }
    return out
