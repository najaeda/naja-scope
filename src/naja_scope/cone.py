# SPDX-License-Identifier: Apache-2.0
"""Cone tracing with structural compression: stop-at-flops, hard max_nodes,
frontier summaries, counts by model. Token-bounding here is a correctness
requirement, not polish (DESIGN.md section 4).

Runs on raw SNL equipotentials: from each pin we build the equipotential,
classify leaf endpoints by direction, and recurse through the model's opposite
terms.
"""

from __future__ import annotations

from collections import deque
from typing import Dict, List

from . import snl
from .errors import ScopeError
from .resolve import Resolved
from .source_index import SrcRange

DEFAULT_MAX_NODES = 200
HARD_MAX_NODES = 1000
MAX_DEPTH = 64
MAX_EDGES_FACTOR = 4


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


def _frontier_summary(root_path: str, frontier: List[dict]) -> dict:
    """Group the stop-at-flops frontier by top-level submodule and flag the
    registers outside the cone root's own subtree.

    This is the cross-hierarchy affordance: the agent's recurring question is
    "does this cone reach register state outside <stage>, and which?". Answering
    it from the flat `frontier` list means re-deriving each path's subtree by
    hand; this block does it once and names the out-of-subtree registers
    directly. Token-bounded: per-subtree counts plus a few example paths, never
    a full dump (DESIGN.md section 4).
    """
    root_subtree = _subtree_key(root_path)
    by_subtree: Dict[str, dict] = {}
    port_count = 0
    for f in frontier:
        if f.get("reason") == "port":
            port_count += 1
            continue
        key = _subtree_key(f["path"])
        bucket = by_subtree.setdefault(key, {"count": 0, "examples": []})
        bucket["count"] += 1
        if len(bucket["examples"]) < 3:
            bucket["examples"].append(f["path"])

    outside = {k: v for k, v in by_subtree.items() if k != root_subtree}
    outside_examples: List[str] = []
    for v in outside.values():
        outside_examples.extend(v["examples"])

    summary = {
        "root_subtree": root_subtree,
        "flop_frontier_count": sum(b["count"] for b in by_subtree.values()),
        "by_subtree": dict(
            sorted(by_subtree.items(), key=lambda kv: -kv[1]["count"])[:20]),
        "outside_root_subtree": {
            "count": sum(v["count"] for v in outside.values()),
            "subtrees": sorted(outside.keys()),
            "examples": outside_examples[:10],
        },
    }
    if port_count:
        summary["top_port_count"] = port_count
    return summary


def trace_cone(resolved: Resolved, session, direction: str,
               stop: str = "flops", max_nodes: int = DEFAULT_MAX_NODES,
               include_edges: bool = True) -> dict:
    if direction not in ("fanin", "fanout"):
        raise ScopeError("direction must be 'fanin' or 'fanout'.")
    if stop not in ("flops", "none"):
        raise ScopeError("stop must be 'flops' or 'none'.")
    max_nodes = max(1, min(max_nodes, HARD_MAX_NODES))
    max_edges = max_nodes * MAX_EDGES_FACTOR

    # Leaf endpoints feeding (fanin) or fed by (fanout) the net; recurse through
    # the model's opposite-direction terms.
    leaf_exclude = snl.DIR_INPUT if direction == "fanin" else snl.DIR_OUTPUT
    top_keep = snl.DIR_OUTPUT if direction == "fanin" else snl.DIR_INPUT
    recurse_dir = snl.DIR_INPUT if direction == "fanin" else snl.DIR_OUTPUT

    nodes: Dict[str, dict] = {}
    edges: List[List[str]] = []
    frontier: List[dict] = []
    counts: Dict[str, int] = {}
    visited = set()
    frontier_seen = set()
    truncated = False

    queue = deque()
    for i, bit in enumerate(_bits_of(resolved)):
        queue.append((bit, resolved.kind, resolved.owner, resolved.path, 0,
                      f"{resolved.path}#{i}"))

    def add_node(inst, ids) -> str:
        path = snl.path_str_from_ids(ids)
        if path not in nodes:
            model = inst.getModel()
            entry = {"path": path, "model": model.getName()}
            try:
                if model.isSequential():
                    entry["seq"] = True
            except Exception:
                pass
            loc = snl.source_loc(inst)
            if loc:
                entry["src"] = SrcRange.from_loc(loc).to_ref()
            nodes[path] = entry
            counts[entry["model"]] = counts.get(entry["model"], 0) + 1
        return path

    def add_edge(a: str, b: str):
        if include_edges and len(edges) < max_edges:
            edges.append([a, b] if direction == "fanin" else [b, a])

    def add_frontier(path: str, reason: str, model: str = None):
        key = (path, reason)
        if key in frontier_seen:
            return
        frontier_seen.add(key)
        entry = {"path": path, "reason": reason}
        if model:
            entry["model"] = model
        frontier.append(entry)

    while queue:
        if len(nodes) >= max_nodes:
            truncated = True
            break
        bit, kind, owner, sink_path, depth, key = queue.popleft()
        if key in visited:
            continue
        visited.add(key)
        eq = snl.build_equipotential(kind, owner, bit)
        if eq is None:
            continue
        for occ in eq.getInstTermOccurrences():
            if len(nodes) >= max_nodes:
                truncated = True
                break
            it = occ.getInstTerm()
            inst = it.getInstance()
            model = inst.getModel()
            if not model.isLeaf() or it.getDirection() == leaf_exclude:
                continue
            ids = list(occ.getPath().getInstanceIDs())
            ids.append(inst.getID())
            path = add_node(inst, ids)
            add_edge(path, sink_path)
            is_seq = False
            try:
                is_seq = model.isSequential()
            except Exception:
                pass
            if is_seq and stop == "flops":
                add_frontier(path, "flop", model.getName())
                continue
            if depth + 1 > MAX_DEPTH:
                add_frontier(path, "max_depth", model.getName())
                continue
            inst_node = snl.node_from_ids(ids)
            for nxt in model.getBitTerms():
                if nxt.getDirection() == recurse_dir:
                    queue.append((nxt, "term", inst_node, path, depth + 1,
                                  f"{path}|{nxt.getName()}"))
        for term in eq.getTerms():
            if term.getDirection() == top_keep:
                continue
            port = f"{snl.top_design().getName()}.{term.getName()}"
            add_frontier(port, "port")

    out = {
        "root": resolved.path,
        "direction": direction,
        "stop": stop,
        "node_count": len(nodes),
        "nodes": list(nodes.values()),
        "frontier": frontier[:200],
        "frontier_summary": _frontier_summary(resolved.path, frontier),
        "counts_by_model": dict(
            sorted(counts.items(), key=lambda kv: -kv[1])[:20]),
        "truncated": truncated or bool(queue),
    }
    if include_edges:
        out["edges"] = edges
        out["edges_truncated"] = len(edges) >= max_edges
    return out
