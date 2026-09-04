# SPDX-License-Identifier: Apache-2.0
"""Drivers/loads through equipotentials — the cross-hierarchy electrical edge
no source-level tool has.

Built on the raw SNLEquipotential in TraverseAssigns mode: lowered assign
instances are transparent, then we classify the remaining inst-term
occurrences by direction and leaf-ness ourselves (the classification the
high-level wrapper used to provide).  Literal constants retain their existing
assign-driver representation.
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


def _leaf_entry(inst_term, id_list, queried_bit=None) -> dict:
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
    constant = snl.assign_constant_value(inst_term)
    if constant is not None:
        entry["constant"] = constant
    if queried_bit is not None:
        entry["bit"] = queried_bit
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


def _constant_assign_driver(resolved: Resolved, bit, queried_bit,
                            value: str):
    """Render the adjacent assign while the main equipotential omits glue.

    TraverseAssigns propagates the constant type but intentionally leaves the
    assign occurrence out of its endpoint set.  A Standard equipotential gives
    us that occurrence so the public constant-driver shape stays compatible.
    """
    eq = snl.build_equipotential(
        resolved.kind, resolved.owner, bit, traverse_assigns=False)
    if eq is None:
        return None
    for occ in eq.getInstTermOccurrences():
        inst_term = occ.getInstTerm()
        inst = inst_term.getInstance()
        if (not inst.getModel().isAssign()
                or inst_term.getDirection() == snl.DIR_INPUT):
            continue
        ids = list(occ.getPath().getInstanceIDs())
        ids.append(inst.getID())
        entry = _leaf_entry(inst_term, ids, queried_bit)
        entry["constant"] = value
        return entry
    return None


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
        queried_bit = None
        if type(bit).__name__ in ("SNLBusNetBit", "SNLBusTermBit"):
            try:
                queried_bit = bit.getBit()
            except Exception:
                pass
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
            entry = _leaf_entry(it, ids, queried_bit)
            key = (entry["path"], entry["pin"])
            if key in seen:
                continue
            seen.add(key)
            if len(leaf) >= limit:
                truncated = True
                break
            leaf.append(entry)
        if want == "drivers" and not truncated:
            value = snl.equipotential_constant_value(eq)
            entry = (_constant_assign_driver(
                resolved, bit, queried_bit, value) if value is not None
                else None)
            if entry is not None:
                key = (entry["path"], entry["pin"])
                if key not in seen:
                    seen.add(key)
                    if len(leaf) >= limit:
                        truncated = True
                    else:
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
