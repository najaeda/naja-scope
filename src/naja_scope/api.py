# SPDX-License-Identifier: Apache-2.0
"""Tool implementations. server.py registers these as MCP tools; tests call
them directly. Every list is paginated, every blob capped (CLAUDE.md rule)."""

from __future__ import annotations

import contextlib
import fnmatch
import io
import os
from typing import List, Optional

from najaeda import naja

from . import cards as cards_mod
from . import cone as cone_mod
from . import connectivity
from . import loader
from . import snl
from .errors import ScopeError
from .paging import clamp_limit, paginate
from .resolve import (Resolved, describe, resolve_path, source_range,
                      source_ref)
from .session import SESSION

MAX_SOURCE_LINES = 120
DEFAULT_SOURCE_CONTEXT = 3
QUERY_OUTPUT_CAP = 8000
# Declaration-aware get_source: how far above a net/term declaration to look for
# an inline enum/struct/typedef block whose members to pull in.
_DECL_MAX_UP = 20
_DECL_KEYWORDS = ("enum", "struct", "union", "typedef")


# -- lifecycle ----------------------------------------------------------------

def _summary(node: snl.InstNode) -> dict:
    return {
        "name": node.name,
        "model": node.model_name,
        "children": node.child_count(),
        "terms": sum(1 for _ in node.design.getTerms()),
        "nets": sum(1 for _ in node.design.getNets()),
    }


# Env opt-in: auto-load the warm intent layer on every load, so a deployment can
# enable get_intent without changing each load call (cf. NAJA_SCOPE_DISABLE_PYTHON).
_INTENT_ENV = "NAJA_SCOPE_INTENT"


def _auto_intent() -> bool:
    return os.environ.get(_INTENT_ENV, "").lower() in ("1", "true", "yes", "on")


def _attach_intent(out: dict, explicit: bool) -> dict:
    """Bring the warm intent layer up for a COLD load (snapshot) by
    re-elaborating from the persisted load_spec, and annotate `out`.

    `explicit` (intent=True passed by the caller) surfaces failures; the env
    opt-in is best-effort — a missing flist must not fail the load, only leave
    get_intent in its graceful "not loaded" state. (Warm SystemVerilog loads
    enable intent inline via keep_ast_link and do not use this path.)
    """
    if not (explicit or _auto_intent()):
        return out
    try:
        SESSION.load_intent()
        out["intent_loaded"] = SESSION.intent_available
    except ScopeError as e:
        if explicit:
            raise
        out["intent_loaded"] = False
        out["intent_note"] = e.message
    return out


def status() -> dict:
    if not SESSION.has_top():
        return {"loaded": False}
    top = SESSION.require_top()
    out = {
        "loaded": True,
        "top": _summary(top),
        "loaded_files": SESSION.loaded_files[:20],
        # Phase-2 intent layer (get_intent): warm-only, so report whether it is
        # live in this session and whether the inputs to (re)load it are known.
        "intent_loaded": SESSION.intent_available,
        "intent_loadable": bool((SESSION.load_spec or {}).get("flist")
                                or (SESSION.load_spec or {}).get("files")),
    }
    return out


def load_systemverilog(files: Optional[List[str]] = None,
                       flist: Optional[str] = None,
                       top: Optional[str] = None,
                       keep_assigns: bool = True,
                       intent: bool = False) -> dict:
    # Warm load: retain the slang AST link inline (keep_ast_link) when intent is
    # requested — no separate elaboration step. Off by default (the Compilation
    # is GB-class on large designs).
    want = bool(intent or _auto_intent())
    top_instance = SESSION.load_systemverilog(files or [], flist=flist,
                                              top=top,
                                              keep_assigns=keep_assigns,
                                              keep_ast_link=want)
    out = {"top": _summary(top_instance)}
    if want:
        out["intent_loaded"] = SESSION.intent_available
        if intent and not SESSION.intent_available:
            out["intent_note"] = ("intent requested but the live AST link is "
                                   "unavailable in this naja build.")
    return out


def load_intent(flist: Optional[str] = None, files: Optional[List[str]] = None,
                top: Optional[str] = None, env: Optional[dict] = None) -> dict:
    """Make the warm intent layer available (naja's in-engine SNL↔slang link).
    A no-op if a load already retained it; otherwise re-elaborates WITH the link
    from the inputs captured at SNL load (or the flist/top passed here). A cold
    snapshot does not carry them, so they must be supplied there."""
    SESSION.require_top()
    SESSION.load_intent(flist=flist, files=files, top=top, env=env)
    return {"intent_loaded": SESSION.intent_available}


def load_verilog(files: List[str], keep_assigns: bool = True,
                 allow_unknown_designs: bool = False) -> dict:
    top_instance = SESSION.load_verilog(
        files, keep_assigns=keep_assigns,
        allow_unknown_designs=allow_unknown_designs)
    return {"top": _summary(top_instance)}


def load_liberty(files: List[str]) -> dict:
    loader.load_liberty(files)
    return {"ok": True}


def load_primitives(name: Optional[str] = None,
                    file: Optional[str] = None) -> dict:
    if name:
        loader.load_primitives(name)
    elif file:
        loader.load_primitives_from_file(file)
    else:
        raise ScopeError("Provide 'name' (xilinx|yosys) or 'file'.")
    return {"ok": True}


def save_snapshot(directory: str) -> dict:
    return SESSION.save_snapshot(directory)


def load_snapshot(directory: str, intent: bool = False) -> dict:
    top_instance = SESSION.load_snapshot(directory)
    # intent re-elaborates from the flist persisted in the snapshot sidecar
    # (the Compilation itself never serializes — see intent.py).
    return _attach_intent({"top": _summary(top_instance)}, explicit=intent)


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
    top_name = top.name
    is_path_pattern = "." in pattern

    def matches_name(name: str, path: str) -> bool:
        if is_path_pattern:
            return fnmatch.fnmatchcase(path, pattern) or fnmatch.fnmatchcase(
                path, f"{top_name}.{pattern}")
        return fnmatch.fnmatchcase(name, pattern)

    def walk():
        if kind in ("module", "any"):
            for design in snl.iter_designs():
                name = design.getName()
                if matches_name(name, name):
                    yield {"kind": "module", "name": name}
        stack = [top]
        while stack:
            node = stack.pop()
            path = node.path
            if kind in ("net", "any"):
                for net in node.design.getNets():
                    n = net.getName()
                    if not n:
                        continue
                    p = f"{path}.{n}"
                    if matches_name(n, p):
                        yield {"kind": "net", "path": p,
                               "width": snl.obj_width(net)}
            if kind in ("port", "any"):
                for term in node.design.getTerms():
                    n = term.getName()
                    p = f"{path}.{n}"
                    if matches_name(n, p):
                        yield {"kind": "term", "path": p,
                               "dir": snl.direction_str(term.getDirection())}
            children = []
            for child in snl.child_nodes(node):
                if kind in ("instance", "any") and matches_name(
                        child.name, child.path):
                    yield {"kind": "instance", "path": child.path,
                           "model": child.model_name}
                if not child.is_leaf():
                    children.append(child)
            stack.extend(reversed(children))

    page, envelope = paginate(walk(), limit=limit, cursor=cursor)
    return {"pattern": pattern, "kind": kind, "matches": page, **envelope}


def get_hierarchy(path: Optional[str] = None, depth: int = 1,
                  limit: Optional[int] = None,
                  cursor: Optional[str] = None) -> dict:
    depth = max(1, min(depth, 5))
    limit = clamp_limit(limit, default=20, maximum=100)
    if path:
        matches = resolve_path(SESSION, path, kind="instance")
        root = matches[0]
    else:
        top = SESSION.require_top()
        root = Resolved("instance", top, top.path, top)

    def node(resolved: Resolved, level: int) -> dict:
        inst = resolved.obj
        out = {"name": inst.name or resolved.path, "model": inst.model_name}
        src = source_ref(resolved, SESSION)
        if src:
            out["src"] = src
        if inst.is_leaf():
            out["leaf"] = True
            return out
        total = inst.child_count()
        out["children_total"] = total
        if level >= depth:
            return out
        # Enumerate only the non-assign children (real submodules + leaf
        # primitives); `assign` glue — the overwhelming majority on a lowered
        # top — is summarized as a count, never dumped. leaf/non-leaf stays a
        # separate axis: each child carries its own `leaf` flag so the agent can
        # tell the 10 submodules from the leaf primitives.
        na = list(snl.non_assign_child_nodes(inst))
        out["assign_count"] = total - len(na)
        out["non_assign_total"] = len(na)
        # Pagination cursor only at the root (unambiguous there); deeper levels
        # fall back to a truncation count.
        page, envelope = paginate(na, limit=limit,
                                  cursor=cursor if level == 0 else None)
        children = [node(Resolved("instance", c, c.path, inst), level + 1)
                    for c in page]
        out["children"] = children
        if level == 0:
            out["next_cursor"] = envelope["next_cursor"]
            out["has_more"] = envelope["has_more"]
        elif envelope["has_more"]:
            out["children_truncated"] = len(na) - len(children)
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


def trace_cone(path: str, direction: str,
               max_frontier: int = cone_mod.DEFAULT_MAX_FRONTIER) -> dict:
    resolved = _resolve_single(path)
    return cone_mod.trace_cone(resolved, SESSION, direction,
                               max_frontier=max_frontier)


# -- source -----------------------------------------------------------------------

def get_source(path: str, context_lines: int = DEFAULT_SOURCE_CONTEXT) -> dict:
    context_lines = max(0, min(context_lines, 20))
    matches = resolve_path(SESSION, path)
    resolved = matches[0]
    rng = source_range(resolved)
    if rng is None:
        return {
            "object": resolved.path,
            "error": "No source range known for this object.",
            "hint": ("Source ranges come from SystemVerilog loading; "
                     "gate-level Verilog without source info has none."),
        }
    file_path = SESSION.find_source_file(rng.file)
    if file_path is None:
        return {"object": resolved.path, "src": rng.to_ref(),
                "error": f"Source file not found: {rng.file}"}
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    start = max(1, rng.line - context_lines)
    end = min(len(lines), rng.end_line + context_lines)
    # Declaration-aware upward window: a net/term source range is a *declaration*
    # (e.g. `} state_q, state_d;`). When an inline `enum`/`struct`/`typedef` block
    # opens just above it, pull that block in so its members (FSM state names,
    # etc.) are visible in one call. Stops at a blank line, and does nothing when
    # the type is referenced (e.g. a package typedef `riscv::priv_lvl_t x;`) with
    # no block above — exactly the case that needs the phase-2 intent layer.
    if resolved.kind in ("net", "term"):
        lo = max(1, rng.line - _DECL_MAX_UP)
        probe = rng.line
        while probe > lo:
            probe -= 1
            stripped = lines[probe - 1].strip()
            if not stripped:
                break
            if any(stripped.startswith(kw) or f" {kw} " in stripped
                   for kw in _DECL_KEYWORDS):
                start = min(start, probe)
                break
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


def _safe_seq(model) -> bool:
    try:
        return bool(model.isSequential())
    except Exception:
        return False


def _collect_model_stats(design, memo: dict) -> dict:
    """Hierarchical stats memoized per model. Deliberately avoids
    najaeda.stats: its is_basic_primitive crashes the process on multi-output
    primitives like naja_fa (see NAJAEDA_NOTES.md)."""
    model_id = design.getID()
    if model_id in memo:
        return memo[model_id]
    entry = {
        "model": _model_label(design.getName()),
        "assigns": 0,
        "leaf_by_model": {},
        "children_by_model": {},
        "flat_leaves": 0,
        "flat_sequential": 0,
    }
    memo[model_id] = entry
    for child in design.getInstances():
        model = child.getModel()
        if model.isAssign():
            entry["assigns"] += 1
        elif model.isLeaf():
            name = _model_label(model.getName())
            entry["leaf_by_model"][name] = (
                entry["leaf_by_model"].get(name, 0) + 1)
            entry["flat_leaves"] += 1
            if _safe_seq(model):
                entry["flat_sequential"] += 1
        else:
            sub = _collect_model_stats(model, memo)
            name = _model_label(model.getName())
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
        design = matches[0].obj.design
    else:
        design = SESSION.require_top().design
    memo: dict = {}
    root = _collect_model_stats(design, memo)
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


# -- intent layer (phase 2) -----------------------------------------------------------

def get_intent(ref: str, want: str = "auto") -> dict:
    """Query the living-intent layer for source-level facts erased by lowering.

    Warm-only (DESIGN.md "Snapshot asymmetry"): if the intent layer is not
    loaded, this degrades gracefully — the structural source range is still
    available via get_source.
    """
    if not SESSION.intent_available:
        return {"intent_loaded": False,
                "note": ("intent layer not loaded; source range is available "
                         "via get_source. Load a warm SystemVerilog session "
                         "with the AST link (load_systemverilog intent=True, "
                         "NAJA_SCOPE_INTENT=1, or load_intent).")}
    ip = SESSION.intent
    try:
        if want == "auto":
            return ip.describe(ref)
        if want == "type":
            return {"intent": "type", **ip.get_type(ref)}
        if want in ("fsm_states", "enum"):
            return {"intent": "fsm_states", **ip.get_fsm_states(ref)}
        if want == "parameters":
            return {"intent": "parameters", **ip.get_parameters(ref)}
        raise ScopeError(
            f"unknown want={want!r}; use auto|type|fsm_states|parameters")
    except ScopeError as e:
        return e.to_dict()


# -- escape hatch ---------------------------------------------------------------------

def query_python(code: str) -> dict:
    """Run najaeda/naja query code against the live session (prep hook 3).
    Read-only by convention; output capped."""
    if os.environ.get("NAJA_SCOPE_DISABLE_PYTHON"):
        raise ScopeError("query_python is disabled "
                         "(NAJA_SCOPE_DISABLE_PYTHON is set).")
    SESSION.require_top()
    buf = io.StringIO()
    # Raw-only escape hatch: `naja` (PySNL bindings), `snl` (naja-scope's raw
    # helper layer: InstNode, top_node, iter_designs, equipotentials), and the
    # live session. No high-level najaeda.netlist here.
    env = {"naja": naja, "snl": snl, "session": SESSION,
           "top": snl.top_node()}
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
