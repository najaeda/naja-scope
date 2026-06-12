# SPDX-License-Identifier: Apache-2.0
"""Cone tracing with structural compression: stop-at-flops, hard max_nodes,
frontier summaries, counts by model. Token-bounding here is a correctness
requirement, not polish (DESIGN.md section 4)."""

from __future__ import annotations

from collections import deque
from typing import Dict, List

from .connectivity import _bits_of, _equipotential_for
from .errors import ScopeError
from .resolve import Resolved, instance_path_str, source_ref
from .session import Session

DEFAULT_MAX_NODES = 200
HARD_MAX_NODES = 1000
MAX_DEPTH = 64
MAX_EDGES_FACTOR = 4


def trace_cone(resolved: Resolved, session: Session, direction: str,
               stop: str = "flops", max_nodes: int = DEFAULT_MAX_NODES,
               include_edges: bool = True) -> dict:
    if direction not in ("fanin", "fanout"):
        raise ScopeError("direction must be 'fanin' or 'fanout'.")
    if stop not in ("flops", "none"):
        raise ScopeError("stop must be 'flops' or 'none'.")
    max_nodes = max(1, min(max_nodes, HARD_MAX_NODES))
    max_edges = max_nodes * MAX_EDGES_FACTOR

    nodes: Dict[str, dict] = {}
    edges: List[List[str]] = []
    frontier: List[dict] = []
    counts: Dict[str, int] = {}
    visited_terms = set()
    frontier_seen = set()
    truncated = False

    # Queue of (bit term/net, path of the node it feeds, depth).
    queue = deque((bit, resolved.path, 0) for bit in _bits_of(resolved))

    def add_node(inst) -> str:
        path = instance_path_str(inst, session)
        if path not in nodes:
            entry = {"path": path, "model": inst.get_model_name()}
            try:
                if inst.is_sequential():
                    entry["seq"] = True
            except Exception:
                pass
            src = source_ref(
                Resolved("instance", inst, path, inst.get_design()), session)
            if src:
                entry["src"] = src
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
        bit, sink_path, depth = queue.popleft()
        bit_key = str(bit)
        if bit_key in visited_terms:
            continue
        visited_terms.add(bit_key)
        eq = _equipotential_for(bit)
        if eq is None:
            continue
        leaf_iter = (eq.get_leaf_drivers() if direction == "fanin"
                     else eq.get_leaf_readers())
        top_iter = (eq.get_top_drivers() if direction == "fanin"
                    else eq.get_top_readers())
        for term in leaf_iter:
            if len(nodes) >= max_nodes:
                truncated = True
                break
            inst = term.get_instance()
            path = add_node(inst)
            add_edge(path, sink_path)
            is_seq = False
            try:
                is_seq = inst.is_sequential()
            except Exception:
                pass
            if is_seq and stop == "flops":
                add_frontier(path, "flop", inst.get_model_name())
                continue
            if depth + 1 > MAX_DEPTH:
                add_frontier(path, "max_depth", inst.get_model_name())
                continue
            next_terms = (inst.get_input_bit_terms() if direction == "fanin"
                          else inst.get_output_bit_terms())
            for nxt in next_terms:
                queue.append((nxt, path, depth + 1))
        for term in top_iter:
            top = session.require_top()
            port = f"{top.get_name()}.{term.get_name()}"
            add_frontier(port, "port")

    if queue and not truncated:
        truncated = len(nodes) >= max_nodes

    out = {
        "root": resolved.path,
        "direction": direction,
        "stop": stop,
        "node_count": len(nodes),
        "nodes": list(nodes.values()),
        "frontier": frontier[:200],
        "counts_by_model": dict(
            sorted(counts.items(), key=lambda kv: -kv[1])[:20]),
        "truncated": truncated or bool(queue),
    }
    if include_edges:
        out["edges"] = edges
        out["edges_truncated"] = len(edges) >= max_edges
    return out
