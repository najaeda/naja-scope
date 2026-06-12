# SPDX-License-Identifier: Apache-2.0
"""Drivers/loads through equipotentials — the cross-hierarchy electrical edge
no source-level tool has (DESIGN.md section 2)."""

from __future__ import annotations

from typing import List, Optional

from .errors import ScopeError
from .resolve import Resolved, instance_path_str, source_ref
from .session import Session

EQ_SIZE_CAP = 5000


def _bits_of(resolved: Resolved) -> List:
    """Bit-level Terms/Nets for a resolved object."""
    obj = resolved.obj
    if resolved.kind in ("term", "net"):
        try:
            if obj.is_bus():
                return list(obj.get_bits())
        except Exception:
            pass
        return [obj]
    raise ScopeError(
        f"'{resolved.path}' is an instance; get_drivers/get_loads expect a "
        "term or net (e.g. a port of it).")


def _equipotential_for(bit) -> Optional[object]:
    """Equipotential for a bit Term or bit Net."""
    if hasattr(bit, "get_equipotential"):
        try:
            return bit.get_equipotential()
        except Exception:
            return None
    # Net: reach the equipotential through any term on the net.
    try:
        for term in bit.get_terms():
            return term.get_equipotential()
    except Exception:
        return None
    return None


def _eq_size(eq) -> object:
    n = 0
    try:
        for _ in eq.get_inst_terms():
            n += 1
            if n >= EQ_SIZE_CAP:
                return f"{EQ_SIZE_CAP}+"
    except Exception:
        return None
    return n


def _leaf_entry(term, session: Session) -> dict:
    inst = term.get_instance()
    entry = {
        "path": instance_path_str(inst, session),
        "model": inst.get_model_name(),
        "pin": term.get_name(),
    }
    try:
        entry["is_sequential"] = inst.is_sequential()
    except Exception:
        pass
    src = source_ref(Resolved("instance", inst, entry["path"],
                              inst.get_design()), session)
    if src:
        entry["src"] = src
    return entry


def _top_entry(term, session: Session) -> dict:
    top = session.require_top()
    return {
        "port": f"{top.get_name()}.{term.get_name()}"
                + (f"[{term.get_bit_number()}]"
                   if _safe_bit(term) is not None else ""),
        "dir": str(term.get_direction()).split(".")[-1].lower(),
    }


def _safe_bit(term):
    try:
        return term.get_bit_number()
    except Exception:
        return None


def endpoints(resolved: Resolved, session: Session, want: str,
              limit: int) -> dict:
    """want is 'drivers' or 'loads'. Walks all bits, dedupes, caps at limit."""
    bits = _bits_of(resolved)
    leaf, top, seen = [], [], set()
    eq_size = None
    truncated = False
    for bit in bits:
        eq = _equipotential_for(bit)
        if eq is None:
            continue
        if eq_size is None and len(bits) == 1:
            eq_size = _eq_size(eq)
        leaf_iter = (eq.get_leaf_drivers() if want == "drivers"
                     else eq.get_leaf_readers())
        top_iter = (eq.get_top_drivers() if want == "drivers"
                    else eq.get_top_readers())
        for term in leaf_iter:
            entry = _leaf_entry(term, session)
            key = (entry["path"], entry["pin"])
            if key in seen:
                continue
            seen.add(key)
            if len(leaf) >= limit:
                truncated = True
                break
            leaf.append(entry)
        for term in top_iter:
            entry = _top_entry(term, session)
            key = ("top", entry["port"])
            if key in seen:
                continue
            seen.add(key)
            if len(top) >= limit:
                truncated = True
                break
            top.append(entry)
        if truncated:
            break
    out = {
        "object": resolved.path,
        "bits_queried": len(bits),
        f"leaf_{want}": leaf,
        f"top_{want}": top,
        "truncated": truncated,
    }
    if eq_size is not None:
        out["equipotential_size"] = eq_size
    return out
