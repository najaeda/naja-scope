# SPDX-License-Identifier: Apache-2.0
"""Stable names for anonymous netlist objects.

SystemVerilog lowering creates anonymous primitive instances (FFs, gates) and
sometimes anonymous nets. Anonymous objects cannot be addressed by hierarchical
path, and the Verilog dumper would invent names we cannot key back to SNL
objects. This pass names them deterministically, once, right after load.

Names are derived from the first driven net (`count_0_dffrn` for the FF driving
count[0]) so they read like the `tx_q_reg` style agents expect.

Renaming happens at the *model* level through raw naja (SNLInstance.setName on
the design's children). najaeda's Instance.set_name would trigger
SNLUniquifier on deep paths — never use it for bulk naming.
"""

from __future__ import annotations

import re

from najaeda import naja


def _direction_is_output(direction) -> bool:
    return "output" in str(direction).lower() or (
        isinstance(direction, int) and direction == 1
    )


def _net_base_name(net) -> str:
    """Name of a net usable as an identifier base; bus bits become name_bit."""
    name = net.getName()
    if name:
        return name
    if hasattr(net, "getBus") and hasattr(net, "getBit"):
        try:
            bus = net.getBus()
            if bus is not None and bus.getName():
                return f"{bus.getName()}_{net.getBit()}"
        except Exception:
            pass
    return ""


_SANITIZE_RE = re.compile(r"\W+")


def _sanitize(name: str) -> str:
    return _SANITIZE_RE.sub("_", name).strip("_")


def _derive_instance_name(inst) -> str:
    model = inst.getModel().getName() or "u"
    base = model[5:] if model.startswith("naja_") else model
    for it in inst.getInstTerms():
        if not _direction_is_output(it.getBitTerm().getDirection()):
            continue
        net = it.getNet()
        if net is None:
            continue
        netname = _sanitize(_net_base_name(net))
        if netname:
            return f"{netname}_{base}"
    return base


def _unique(base: str, used: set) -> str:
    if base not in used:
        return base
    i = 2
    while f"{base}_{i}" in used:
        i += 1
    return f"{base}_{i}"


def _iter_designs():
    universe = naja.NLUniverse.get()
    if universe is None:
        return
    db = universe.getTopDB()
    if db is None:
        return
    for lib in db.getLibraries():
        if lib.isPrimitives():
            continue
        for design in lib.getSNLDesigns():
            yield design


def ensure_names() -> dict:
    """Name all anonymous instances and nets. Idempotent. Returns counts."""
    named_instances = 0
    named_nets = 0
    for design in _iter_designs():
        used = {inst.getName() for inst in design.getInstances()}
        for inst in design.getInstances():
            if inst.getName():
                continue
            name = _unique(_derive_instance_name(inst), used)
            inst.setName(name)
            used.add(name)
            named_instances += 1
        used_nets = {net.getName() for net in design.getNets()}
        for net in design.getNets():
            if net.getName():
                continue
            try:
                ident = net.getID()
            except Exception:
                ident = named_nets
            name = _unique(f"n_{ident}", used_nets)
            try:
                net.setName(name)
                used_nets.add(name)
                named_nets += 1
            except Exception:
                continue
    return {"named_instances": named_instances, "named_nets": named_nets}
