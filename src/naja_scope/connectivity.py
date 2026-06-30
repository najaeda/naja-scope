# SPDX-License-Identifier: Apache-2.0
"""Drivers/loads through equipotentials — the cross-hierarchy electrical edge
no source-level tool has.

Built on the raw SNLEquipotential: we classify inst-term occurrences by
direction and leaf-ness ourselves (the classification the high-level wrapper
used to provide), so naja-scope owns the connectivity semantics end to end.
"""

from __future__ import annotations

from typing import List

from . import snl
from .errors import ScopeError
from .resolve import Resolved
from .source_index import SrcRange

EQ_SIZE_CAP = 5000


def _bits_of(resolved: Resolved) -> List:
    """Bit-level terms/nets for a resolved object."""
    if resolved.kind in ("term", "net"):
        return snl.obj_bits(resolved.obj)
    raise ScopeError(
        f"'{resolved.path}' is an instance; get_drivers/get_loads expect a "
        "term or net (e.g. a port of it).")


def _leaf_entry(inst_term, id_list) -> dict:
    inst = inst_term.getInstance()
    model = inst.getModel()
    entry = {
        "path": snl.path_str_from_ids(id_list),
        "label": snl.friendly_label(inst),
        "model": model.getName(),
        "pin": inst_term.getBitTerm().getName(),
    }
    try:
        entry["is_sequential"] = model.isSequential()
    except Exception:
        pass
    loc = snl.source_loc(inst)
    if loc:
        entry["src"] = SrcRange.from_loc(loc).to_ref()
    return entry


def _top_entry(term) -> dict:
    top_name = snl.top_design().getName()
    bit = None
    if type(term).__name__ == "SNLBusTermBit":
        try:
            bit = term.getBit()
        except Exception:
            bit = None
    port = f"{top_name}.{term.getName()}" + (f"[{bit}]" if bit is not None else "")
    return {"port": port, "dir": snl.direction_str(term.getDirection())}


def endpoints(resolved: Resolved, session, want: str, limit: int) -> dict:
    """want is 'drivers' or 'loads'. Walks all bits, dedupes, caps at limit."""
    bits = _bits_of(resolved)
    # Leaf-side: drivers exclude pure inputs; loads exclude pure outputs.
    leaf_exclude = snl.DIR_INPUT if want == "drivers" else snl.DIR_OUTPUT
    # Top-side ports: a top input drives the net; a top output reads it.
    top_exclude = snl.DIR_OUTPUT if want == "drivers" else snl.DIR_INPUT

    leaf, top, seen = [], [], set()
    eq_size = None
    truncated = False
    for bit in bits:
        eq = snl.build_equipotential(resolved.kind, resolved.owner, bit)
        if eq is None:
            continue
        if eq_size is None and len(bits) == 1:
            eq_size = snl.equi_size(eq, EQ_SIZE_CAP)
        for occ in eq.getInstTermOccurrences():
            it = occ.getInstTerm()
            inst = it.getInstance()
            if not inst.getModel().isLeaf():
                continue
            if it.getDirection() == leaf_exclude:
                continue
            ids = list(occ.getPath().getInstanceIDs())
            ids.append(inst.getID())
            entry = _leaf_entry(it, ids)
            key = (entry["path"], entry["pin"])
            if key in seen:
                continue
            seen.add(key)
            if len(leaf) >= limit:
                truncated = True
                break
            leaf.append(entry)
        for term in eq.getTerms():
            if term.getDirection() == top_exclude:
                continue
            entry = _top_entry(term)
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
