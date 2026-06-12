# SPDX-License-Identifier: Apache-2.0
"""Tool implementations. server.py registers these as MCP tools; tests call
them directly. Every list is paginated, every blob capped (CLAUDE.md rule)."""

from __future__ import annotations

import contextlib
import fnmatch
import io
import os
from typing import List, Optional

from najaeda import naja, netlist

from . import cards as cards_mod
from . import cone as cone_mod
from . import connectivity
from .errors import ScopeError
from .paging import clamp_limit, paginate
from .resolve import Resolved, describe, resolve_path, source_ref
from .session import SESSION

MAX_SOURCE_LINES = 120
DEFAULT_SOURCE_CONTEXT = 3
QUERY_OUTPUT_CAP = 8000


# -- lifecycle ----------------------------------------------------------------

def _summary(instance: netlist.Instance) -> dict:
    return {
        "name": instance.get_name(),
        "model": instance.get_model_name(),
        "children": instance.count_child_instances(),
        "terms": instance.count_terms(),
        "nets": instance.count_nets(),
    }


def status() -> dict:
    if not SESSION.has_top():
        return {"loaded": False}
    top = SESSION.require_top()
    out = {
        "loaded": True,
        "top": _summary(top),
        "loaded_files": SESSION.loaded_files[:20],
        "naming": SESSION.naming_stats,
        "source_index": (SESSION.source_index.stats()
                         if SESSION.source_index is not None
                         else "not built yet (built lazily on first source query)"),
    }
    return out


def load_systemverilog(files: Optional[List[str]] = None,
                       flist: Optional[str] = None,
                       top: Optional[str] = None,
                       keep_assigns: bool = True) -> dict:
    top_instance = SESSION.load_systemverilog(files or [], flist=flist,
                                              top=top,
                                              keep_assigns=keep_assigns)
    return {"top": _summary(top_instance), "naming": SESSION.naming_stats}


def load_verilog(files: List[str], keep_assigns: bool = True,
                 allow_unknown_designs: bool = False) -> dict:
    top_instance = SESSION.load_verilog(
        files, keep_assigns=keep_assigns,
        allow_unknown_designs=allow_unknown_designs)
    return {"top": _summary(top_instance), "naming": SESSION.naming_stats}


def load_liberty(files: List[str]) -> dict:
    netlist.load_liberty(files)
    return {"ok": True}


def load_primitives(name: Optional[str] = None,
                    file: Optional[str] = None) -> dict:
    if name:
        netlist.load_primitives(name)
    elif file:
        netlist.load_primitives_from_file(file)
    else:
        raise ScopeError("Provide 'name' (xilinx|yosys) or 'file'.")
    return {"ok": True}


def save_snapshot(directory: str) -> dict:
    return SESSION.save_snapshot(directory)


def load_snapshot(directory: str) -> dict:
    top_instance = SESSION.load_snapshot(directory)
    return {"top": _summary(top_instance),
            "source_index": (SESSION.source_index.stats()
                             if SESSION.source_index else None)}


def reset_universe() -> dict:
    SESSION.reset()
    return {"ok": True}


# -- navigation ----------------------------------------------------------------

def resolve(path: str, kind: Optional[str] = None,
            limit: Optional[int] = None) -> dict:
    limit = clamp_limit(limit, default=20)
    matches = resolve_path(SESSION, path, kind=kind)
    described = [describe(m, SESSION) for m in matches[:limit]]
    return {"matches": described,
            "truncated": len(matches) > limit}


def find(pattern: str, kind: str = "any", limit: Optional[int] = None,
         cursor: Optional[str] = None) -> dict:
    """DFS over the hierarchy matching names (and full paths if the pattern
    contains a dot). kind: instance|net|port|module|any."""
    if kind not in ("instance", "net", "port", "module", "any"):
        raise ScopeError("kind must be instance|net|port|module|any.")
    top = SESSION.require_top()
    top_name = top.get_name()
    is_path_pattern = "." in pattern

    def matches_name(name: str, path: str) -> bool:
        if is_path_pattern:
            return fnmatch.fnmatchcase(path, pattern) or fnmatch.fnmatchcase(
                path, f"{top_name}.{pattern}")
        return fnmatch.fnmatchcase(name, pattern)

    def walk():
        if kind in ("module", "any"):
            for design in cards_mod._all_designs():
                name = design.getName()
                if matches_name(name, name):
                    yield {"kind": "module", "name": name}
        stack = [(top, top_name)]
        while stack:
            inst, path = stack.pop()
            if kind in ("net", "any"):
                for net in inst.get_nets():
                    n = net.get_name()
                    p = f"{path}.{n}"
                    if matches_name(n, p):
                        yield {"kind": "net", "path": p,
                               "width": net.get_width()}
            if kind in ("port", "any"):
                for term in inst.get_terms():
                    n = term.get_name()
                    p = f"{path}.{n}"
                    if matches_name(n, p):
                        yield {"kind": "term", "path": p,
                               "dir": str(term.get_direction()
                                          ).split(".")[-1].lower()}
            children = []
            for child in inst.get_child_instances():
                n = child.get_name()
                p = f"{path}.{n}"
                if kind in ("instance", "any") and matches_name(n, p):
                    yield {"kind": "instance", "path": p,
                           "model": child.get_model_name()}
                if not child.is_leaf():
                    children.append((child, p))
            stack.extend(reversed(children))

    page, envelope = paginate(walk(), limit=limit, cursor=cursor)
    return {"pattern": pattern, "kind": kind, "matches": page, **envelope}


def get_hierarchy(path: Optional[str] = None, depth: int = 1,
                  limit: Optional[int] = None) -> dict:
    depth = max(1, min(depth, 5))
    limit = clamp_limit(limit, default=20, maximum=100)
    if path:
        matches = resolve_path(SESSION, path, kind="instance")
        root = matches[0]
    else:
        top = SESSION.require_top()
        root = Resolved("instance", top, top.get_name(), top)

    def node(resolved: Resolved, level: int) -> dict:
        inst = resolved.obj
        out = {"name": inst.get_name() or resolved.path,
               "model": inst.get_model_name()}
        src = source_ref(resolved, SESSION)
        if src:
            out["src"] = src
        if inst.is_leaf():
            out["leaf"] = True
            return out
        total = inst.count_child_instances()
        out["children_total"] = total
        if level >= depth:
            return out
        children = []
        shown = 0
        for child in inst.get_child_instances():
            if shown >= limit:
                out["children_truncated"] = total - shown
                break
            child_resolved = Resolved(
                "instance", child, f"{resolved.path}.{child.get_name()}",
                inst)
            children.append(node(child_resolved, level + 1))
            shown += 1
        out["children"] = children
        return out

    return {"root": node(root, 0), "depth": depth}


# -- connectivity ---------------------------------------------------------------

def _resolve_single(path: str, kinds=("term", "net")) -> Resolved:
    matches = resolve_path(SESSION, path)
    for kind in kinds:
        for m in matches:
            if m.kind == kind:
                return m
    return matches[0]


def get_drivers(path: str, limit: Optional[int] = None) -> dict:
    resolved = _resolve_single(path)
    return connectivity.endpoints(resolved, SESSION, "drivers",
                                  clamp_limit(limit))


def get_loads(path: str, limit: Optional[int] = None) -> dict:
    resolved = _resolve_single(path)
    return connectivity.endpoints(resolved, SESSION, "loads",
                                  clamp_limit(limit))


def trace_cone(path: str, direction: str, stop: str = "flops",
               max_nodes: int = cone_mod.DEFAULT_MAX_NODES,
               include_edges: bool = True) -> dict:
    resolved = _resolve_single(path)
    return cone_mod.trace_cone(resolved, SESSION, direction, stop=stop,
                               max_nodes=max_nodes,
                               include_edges=include_edges)


# -- source -----------------------------------------------------------------------

def get_source(path: str, context_lines: int = DEFAULT_SOURCE_CONTEXT) -> dict:
    context_lines = max(0, min(context_lines, 20))
    matches = resolve_path(SESSION, path)
    resolved = matches[0]
    ref = source_ref(resolved, SESSION)
    if not ref:
        return {
            "object": resolved.path,
            "error": "No source range known for this object.",
            "hint": ("Source ranges come from SystemVerilog loading; "
                     "gate-level Verilog without sv_src_* attributes has none."),
        }
    index = SESSION.get_source_index()
    rng = None
    if resolved.kind == "instance":
        if resolved.obj.is_top():
            rng = index.module_range(resolved.obj.get_model_name())
        else:
            parent = resolved.obj.get_design()
            rng = index.instance_range(parent.get_model_name(),
                                       resolved.obj.get_name())
    elif resolved.kind == "net":
        rng = index.net_range(resolved.owner.get_model_name(),
                              resolved.obj.get_name())
    elif resolved.kind == "term":
        owner = resolved.owner
        if owner.is_top():
            rng = index.module_range(owner.get_model_name())
        else:
            rng = index.instance_range(owner.get_design().get_model_name(),
                                       owner.get_name())
    if rng is None:
        return {"object": resolved.path,
                "error": "No source range known for this object."}
    file_path = SESSION.find_source_file(rng.file)
    if file_path is None:
        return {"object": resolved.path, "src": rng.to_ref(),
                "error": f"Source file not found: {rng.file}"}
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    start = max(1, rng.line - context_lines)
    end = min(len(lines), rng.end_line + context_lines)
    selected = lines[start - 1:end]
    truncated = False
    if len(selected) > MAX_SOURCE_LINES:
        head = selected[:MAX_SOURCE_LINES // 2]
        tail = selected[-MAX_SOURCE_LINES // 2:]
        omitted = len(selected) - len(head) - len(tail)
        selected = head + [f"... ({omitted} lines omitted) ...\n"] + tail
        truncated = True
    return {
        "object": resolved.path,
        "file": file_path,
        "start": start,
        "end": end,
        "src": rng.to_ref(),
        "text": "".join(selected),
        "truncated": truncated,
    }


# -- summaries ---------------------------------------------------------------------

def get_module_card(module: str) -> dict:
    return cards_mod.module_card(SESSION, module)


def _model_label(name: str) -> str:
    return name or "(unnamed)"


def _safe_seq(instance) -> bool:
    try:
        return bool(instance.is_sequential())
    except Exception:
        return False


def _collect_model_stats(instance, memo: dict) -> dict:
    """Hierarchical stats memoized per model. Deliberately avoids
    najaeda.stats: its is_basic_primitive crashes the process on multi-output
    primitives like naja_fa (see NAJAEDA_NOTES.md)."""
    model_id = instance.get_model_id()
    if model_id in memo:
        return memo[model_id]
    entry = {
        "model": _model_label(instance.get_model_name()),
        "assigns": 0,
        "leaf_by_model": {},
        "children_by_model": {},
        "flat_leaves": 0,
        "flat_sequential": 0,
    }
    memo[model_id] = entry
    for child in instance.get_child_instances():
        if child.is_assign():
            entry["assigns"] += 1
        elif child.is_leaf():
            name = _model_label(child.get_model_name())
            entry["leaf_by_model"][name] = (
                entry["leaf_by_model"].get(name, 0) + 1)
            entry["flat_leaves"] += 1
            if _safe_seq(child):
                entry["flat_sequential"] += 1
        else:
            sub = _collect_model_stats(child, memo)
            name = _model_label(child.get_model_name())
            entry["children_by_model"][name] = (
                entry["children_by_model"].get(name, 0) + 1)
            entry["flat_leaves"] += sub["flat_leaves"]
            entry["flat_sequential"] += sub["flat_sequential"]
    return entry


def get_stats(path: Optional[str] = None, limit: Optional[int] = None,
              cursor: Optional[str] = None) -> dict:
    limit = clamp_limit(limit, default=25)
    if path:
        matches = resolve_path(SESSION, path, kind="instance")
        instance = matches[0].obj
    else:
        instance = SESSION.require_top()
    memo: dict = {}
    root = _collect_model_stats(instance, memo)
    models = sorted(memo.values(), key=lambda m: -m["flat_leaves"])
    for m in models:
        m["leaf_by_model"] = dict(sorted(
            m["leaf_by_model"].items(), key=lambda kv: -kv[1])[:12])
    page, envelope = paginate(models, limit=limit, cursor=cursor)
    return {
        "root_model": root["model"],
        "flat_leaves": root["flat_leaves"],
        "flat_sequential": root["flat_sequential"],
        "models": page,
        "total_models": len(models),
        **envelope,
    }


# -- escape hatch ---------------------------------------------------------------------

def query_python(code: str) -> dict:
    """Run najaeda/naja query code against the live session (prep hook 3).
    Read-only by convention; output capped."""
    if os.environ.get("NAJA_SCOPE_DISABLE_PYTHON"):
        raise ScopeError("query_python is disabled "
                         "(NAJA_SCOPE_DISABLE_PYTHON is set).")
    SESSION.require_top()
    buf = io.StringIO()
    env = {"netlist": netlist, "naja": naja, "session": SESSION,
           "get_top": netlist.get_top}
    result_repr = None
    with contextlib.redirect_stdout(buf):
        try:
            try:
                result_repr = repr(eval(code, env))
            except SyntaxError:
                exec(code, env)
        except Exception as e:  # report, don't crash the server
            return {"error": f"{type(e).__name__}: {e}",
                    "stdout": _cap(buf.getvalue())}
    out = {"stdout": _cap(buf.getvalue())}
    if result_repr is not None:
        out["result"] = _cap(result_repr)
    return out


def _cap(text: str) -> str:
    if len(text) <= QUERY_OUTPUT_CAP:
        return text
    return (text[:QUERY_OUTPUT_CAP]
            + f"\n... (truncated, {len(text) - QUERY_OUTPUT_CAP} chars omitted)")
