# SPDX-License-Identifier: Apache-2.0
"""Hierarchical path resolution — the make-or-break tool.

Paths are dot-separated: `top.u_uart.tx_q_reg`, `top.u_cnt.count[3]`. The top
segment is optional. The final segment may be an instance, a term (port of the
instance reached so far), or a net (inside the design of the instance reached
so far), with an optional bit select. A failed segment produces did-you-mean
suggestions instead of a bare error; the final segment may use glob patterns.

Everything here runs on the raw SNL layer via `snl` (InstNode + raw terms/nets).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from . import snl
from .errors import ResolveError, ScopeError
from .source_index import SrcRange

_BIT_RE = re.compile(r"^(.*)\[(-?\d+)\]$")
_MAX_SUGGESTION_SCAN = 2000


def split_path(path: str) -> List[str]:
    """Split on dots, but not inside brackets (net[3] stays one segment)."""
    segments, buf, depth = [], [], 0
    for ch in path:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth = max(0, depth - 1)
        if ch == "." and depth == 0:
            if buf:
                segments.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if buf:
        segments.append("".join(buf))
    return segments


@dataclass
class Resolved:
    kind: str                  # "instance" | "term" | "net"
    obj: object                # snl.InstNode | raw SNL term/net (bit if selected)
    path: str                  # canonical path including top name
    owner: snl.InstNode        # InstNode owning the term/net (or the parent)
    bit: Optional[int] = None  # explicit bit select, if any


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


def describe(resolved: Resolved, session=None) -> dict:
    """Compact descriptor dict for one resolved object."""
    out = {"kind": resolved.kind, "path": resolved.path}
    obj = resolved.obj
    if resolved.kind == "instance":
        out["model"] = obj.model_name
        out["is_leaf"] = obj.is_leaf()
        if obj.is_leaf():
            out["is_sequential"] = _safe(obj.is_sequential)
        else:
            out["children"] = obj.child_count()
    elif resolved.kind == "term":
        out["dir"] = snl.direction_str(obj.getDirection())
        out["width"] = snl.obj_width(obj)
        if resolved.bit is not None:
            out["bit"] = resolved.bit
    elif resolved.kind == "net":
        out["width"] = snl.obj_width(obj)
        if resolved.bit is not None:
            out["bit"] = resolved.bit
    src = source_ref(resolved, session)
    if src:
        out["src"] = src
    return out


def source_range(resolved: Resolved) -> Optional[SrcRange]:
    """SrcRange for a resolved object, straight from getSourceLoc()."""
    if resolved.kind == "instance":
        loc = resolved.obj.source_loc()
    else:
        loc = snl.source_loc(resolved.obj)
        if loc is None and resolved.owner is not None:
            loc = resolved.owner.source_loc()
    return SrcRange.from_loc(loc) if loc else None


def source_ref(resolved: Resolved, session=None) -> Optional[str]:
    """`file:start-end` for a resolved object, straight from getSourceLoc()."""
    rng = source_range(resolved)
    return rng.to_ref() if rng else None


def _level_names(node: snl.InstNode, cap: int = _MAX_SUGGESTION_SCAN):
    """(child names, term names, net names) visible at one hierarchy level."""
    children, terms, nets = [], [], []
    for inst in node.design.getInstances():
        children.append(snl.inst_segment(inst))
        if len(children) >= cap:
            break
    for term in node.design.getTerms():
        terms.append(term.getName())
        if len(terms) >= cap:
            break
    for net in node.design.getNets():
        name = net.getName()
        if name:  # anonymous nets have no addressable name
            nets.append(name)
        if len(nets) >= cap:
            break
    return children, terms, nets


def _suggest(segment: str, node: snl.InstNode) -> List[str]:
    import difflib
    children, terms, nets = _level_names(node)
    pool = children + terms + nets
    close = difflib.get_close_matches(segment, pool, n=8, cutoff=0.5)
    lowered = segment.lower()
    for name in pool:
        if lowered in name.lower() and name not in close:
            close.append(name)
        if len(close) >= 8:
            break
    return close[:8]


def _match_segment(node: snl.InstNode, segment: str, is_last: bool,
                   prefix: str) -> List[Resolved]:
    """All objects a segment can denote at this level."""
    matches: List[Resolved] = []
    m = _BIT_RE.match(segment)

    def add_instance(child: snl.InstNode):
        matches.append(Resolved("instance", child, child.path, node))

    def add_term(term, bit_sel):
        obj = term
        if bit_sel is not None:
            picked = snl.term_bit(term, bit_sel)
            if picked is None:
                return
            obj = picked
        matches.append(Resolved("term", obj, f"{prefix}.{segment}",
                                node, bit_sel))

    def add_net(net, bit_sel):
        obj = net
        if bit_sel is not None:
            picked = snl.net_bit(net, bit_sel)
            if picked is None:
                return
            obj = picked
        matches.append(Resolved("net", obj, f"{prefix}.{segment}",
                                node, bit_sel))

    # Literal name first (covers names that legitimately contain brackets).
    child = snl.child_node(node, segment)
    if child is not None:
        add_instance(child)
    if is_last:
        term = node.design.getTerm(segment)
        if term is not None:
            add_term(term, None)
        net = node.design.getNet(segment)
        if net is not None:
            add_net(net, None)
    # Bit-select interpretation.
    if m and not matches:
        base, bit = m.group(1), int(m.group(2))
        if is_last:
            term = node.design.getTerm(base)
            if term is not None:
                add_term(term, bit)
            net = node.design.getNet(base)
            if net is not None:
                add_net(net, bit)
    # Glob in the final segment.
    if is_last and not matches and any(c in segment for c in "*?["):
        import fnmatch
        children, terms, nets = _level_names(node)
        for name in children:
            if fnmatch.fnmatchcase(name, segment):
                c = snl.child_node(node, name)
                if c is not None:
                    add_instance(c)
        for name in terms:
            if fnmatch.fnmatchcase(name, segment):
                t = node.design.getTerm(name)
                if t is not None:
                    matches.append(Resolved("term", t, f"{prefix}.{name}", node))
        for name in nets:
            if fnmatch.fnmatchcase(name, segment):
                n = node.design.getNet(name)
                if n is not None:
                    matches.append(Resolved("net", n, f"{prefix}.{name}", node))
    return matches


def resolve_path(session, path: str,
                 kind: Optional[str] = None) -> List[Resolved]:
    """Resolve a path to objects; raises ResolveError with suggestions."""
    session.require_top()
    top = snl.top_node()
    top_name = top.name
    segments = split_path(path.strip())
    if not segments:
        raise ScopeError("Empty path.")
    if segments[0] == top_name:
        segments = segments[1:]
    if not segments:
        return [Resolved("instance", top, top_name, top)]

    node = top
    prefix = top_name
    for i, segment in enumerate(segments):
        is_last = i == len(segments) - 1
        matches = _match_segment(node, segment, is_last, prefix)
        if not matches:
            raise ResolveError(path, segment, _suggest(segment, node))
        if not is_last:
            inst_matches = [m for m in matches if m.kind == "instance"]
            if not inst_matches:
                raise ResolveError(path, segment, _suggest(segment, node))
            node = inst_matches[0].obj
            prefix = inst_matches[0].path
        else:
            if kind:
                matches = [m for m in matches if m.kind == kind]
                if not matches:
                    raise ResolveError(path, segment, _suggest(segment, node))
            return matches
    raise ResolveError(path, segments[-1])


def instance_path_str(node: snl.InstNode, session=None) -> str:
    return node.path
