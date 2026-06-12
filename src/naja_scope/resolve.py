# SPDX-License-Identifier: Apache-2.0
"""Hierarchical path resolution — the make-or-break tool (DESIGN.md section 3).

Paths are dot-separated: `top.u_uart.tx_q_reg`, `top.u_cnt.count[3]`. The top
segment is optional. The final segment may be an instance, a term (port of the
instance reached so far), or a net (inside the design of the instance reached
so far), with an optional bit select. A failed segment produces did-you-mean
suggestions instead of a bare error; the final segment may use glob patterns.
"""

from __future__ import annotations

import difflib
import fnmatch
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from najaeda import netlist

from .errors import ResolveError, ScopeError
from .session import Session

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
    kind: str                      # "instance" | "term" | "net"
    obj: object                    # najaeda Instance | Term | Net
    path: str                      # canonical path including top name
    owner: object                  # Instance owning the term/net (or parent)
    bit: Optional[int] = None      # explicit bit select, if any


def _direction_str(term) -> Optional[str]:
    try:
        return str(term.get_direction()).split(".")[-1].lower()
    except Exception:
        return None


def _instance_path(instance: netlist.Instance, top_name: str) -> str:
    chain = []
    cursor = instance
    while cursor is not None and not cursor.is_top():
        chain.append(cursor.get_name())
        cursor = cursor.get_design()
    chain.append(top_name)
    return ".".join(reversed(chain))


def describe(resolved: Resolved, session: Session) -> dict:
    """Compact descriptor dict for one resolved object."""
    out = {"kind": resolved.kind, "path": resolved.path}
    obj = resolved.obj
    if resolved.kind == "instance":
        out["model"] = obj.get_model_name()
        out["is_leaf"] = obj.is_leaf()
        if obj.is_leaf():
            out["is_sequential"] = _safe(obj.is_sequential)
        else:
            out["children"] = obj.count_child_instances()
    elif resolved.kind == "term":
        out["dir"] = _direction_str(obj)
        out["width"] = _safe(obj.get_width)
        if resolved.bit is not None:
            out["bit"] = resolved.bit
    elif resolved.kind == "net":
        out["width"] = _safe(obj.get_width)
        if resolved.bit is not None:
            out["bit"] = resolved.bit
    src = source_ref(resolved, session)
    if src:
        out["src"] = src
    return out


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


def source_ref(resolved: Resolved, session: Session) -> Optional[str]:
    """`file:start-end` for a resolved object, if the index knows it."""
    try:
        index = session.get_source_index()
    except ScopeError:
        return None
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
            parent = owner.get_design()
            rng = index.instance_range(parent.get_model_name(),
                                       owner.get_name())
    return rng.to_ref() if rng else None


def _level_names(instance: netlist.Instance, cap: int = _MAX_SUGGESTION_SCAN):
    """(child names, term names, net names) visible at one hierarchy level."""
    children, terms, nets = [], [], []
    for child in instance.get_child_instances():
        children.append(child.get_name())
        if len(children) >= cap:
            break
    for term in instance.get_terms():
        terms.append(term.get_name())
        if len(terms) >= cap:
            break
    for net in instance.get_nets():
        nets.append(net.get_name())
        if len(nets) >= cap:
            break
    return children, terms, nets


def _suggest(segment: str, instance: netlist.Instance) -> List[str]:
    children, terms, nets = _level_names(instance)
    pool = children + terms + nets
    close = difflib.get_close_matches(segment, pool, n=8, cutoff=0.5)
    lowered = segment.lower()
    for name in pool:
        if lowered in name.lower() and name not in close:
            close.append(name)
        if len(close) >= 8:
            break
    return close[:8]


def _match_segment(instance: netlist.Instance, segment: str, is_last: bool,
                   top_name: str, prefix: str) -> List[Resolved]:
    """All objects a segment can denote at this level."""
    matches: List[Resolved] = []
    base, bit = segment, None
    m = _BIT_RE.match(segment)

    def add_instance(child):
        matches.append(Resolved("instance", child,
                                f"{prefix}.{child.get_name()}", instance))

    def add_term(term, bit_sel):
        obj = term
        if bit_sel is not None:
            picked = term.get_bit(bit_sel) if term.is_bus() else None
            if picked is None:
                return
            obj = picked
        matches.append(Resolved("term", obj, f"{prefix}.{segment}",
                                instance, bit_sel))

    def add_net(net, bit_sel):
        obj = net
        if bit_sel is not None:
            picked = net.get_bit(bit_sel) if net.is_bus() else None
            if picked is None:
                return
            obj = picked
        matches.append(Resolved("net", obj, f"{prefix}.{segment}",
                                instance, bit_sel))

    # Literal name first (covers names that legitimately contain brackets).
    child = instance.get_child_instance(base)
    if child is not None:
        add_instance(child)
    if is_last:
        term = _safe(lambda: instance.get_term(base))
        if term is not None:
            add_term(term, None)
        net = _safe(lambda: instance.get_net(base))
        if net is not None:
            add_net(net, None)
    # Bit-select interpretation.
    if m and not matches:
        base, bit = m.group(1), int(m.group(2))
        if is_last:
            term = _safe(lambda: instance.get_term(base))
            if term is not None:
                add_term(term, bit)
            net = _safe(lambda: instance.get_net(base))
            if net is not None:
                add_net(net, bit)
    # Glob in the final segment.
    if is_last and not matches and any(c in segment for c in "*?["):
        children, terms, nets = _level_names(instance)
        for name in children:
            if fnmatch.fnmatchcase(name, segment):
                c = instance.get_child_instance(name)
                if c is not None:
                    add_instance(c)
        for name in terms:
            if fnmatch.fnmatchcase(name, segment):
                t = _safe(lambda: instance.get_term(name))
                if t is not None:
                    matches.append(Resolved("term", t, f"{prefix}.{name}",
                                            instance))
        for name in nets:
            if fnmatch.fnmatchcase(name, segment):
                n = _safe(lambda: instance.get_net(name))
                if n is not None:
                    matches.append(Resolved("net", n, f"{prefix}.{name}",
                                            instance))
    return matches


def resolve_path(session: Session, path: str,
                 kind: Optional[str] = None) -> List[Resolved]:
    """Resolve a path to objects; raises ResolveError with suggestions."""
    top = session.require_top()
    top_name = top.get_name()
    segments = split_path(path.strip())
    if not segments:
        raise ScopeError("Empty path.")
    if segments[0] == top_name:
        segments = segments[1:]
    if not segments:
        return [Resolved("instance", top, top_name, top)]

    instance = top
    prefix = top_name
    for i, segment in enumerate(segments):
        is_last = i == len(segments) - 1
        matches = _match_segment(instance, segment, is_last, top_name, prefix)
        if not matches:
            raise ResolveError(path, segment, _suggest(segment, instance))
        if not is_last:
            inst_matches = [m for m in matches if m.kind == "instance"]
            if not inst_matches:
                raise ResolveError(path, segment, _suggest(segment, instance))
            instance = inst_matches[0].obj
            prefix = inst_matches[0].path
        else:
            if kind:
                matches = [m for m in matches if m.kind == kind]
                if not matches:
                    raise ResolveError(path, segment,
                                       _suggest(segment, instance))
            return matches
    raise ResolveError(path, segments[-1])


def instance_path_str(instance: netlist.Instance, session: Session) -> str:
    top = session.require_top()
    return _instance_path(instance, top.get_name())
