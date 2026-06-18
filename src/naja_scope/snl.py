# SPDX-License-Identifier: Apache-2.0
"""Raw SNL access layer.

naja-scope is built directly on the raw `naja` bindings — the Python interface
to the SNL C++ API — not on the najaeda high-level `netlist` wrappers. The
high-level layer is a human-ergonomics simplification; the raw layer is more
complete (parameters, design/library enumeration, occurrence/path control) and
is the natural substrate for the phase-2 slang-AST coupling.

This module centralises every raw-SNL primitive the tools need:

* universe / top / design enumeration,
* source locations (getSourceLoc),
* `InstNode` — a hierarchical instance occurrence carrying both a name-path
  (for display) and an `SNLPath` (for occurrence/equipotential construction),
* term/net bit handling,
* equipotential construction and leaf/top classification.

High-level najaeda is used only at the load boundary (session.py) and inside
the query_python escape hatch.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple

from najaeda import naja

# Direction enum values (verified: Input == 0, Output == 1, Inout == 2).
DIR_INPUT = naja.SNLTerm.Direction.Input
DIR_OUTPUT = naja.SNLTerm.Direction.Output

_BUS_TYPES = {"SNLBusTerm", "SNLBusNet"}


# -- universe / designs ------------------------------------------------------

def universe():
    return naja.NLUniverse.get()


def has_top() -> bool:
    u = universe()
    return u is not None and u.getTopDesign() is not None


def top_design():
    u = universe()
    return u.getTopDesign() if u is not None else None


def top_db():
    u = universe()
    return u.getTopDB() if u is not None else None


def iter_designs(include_primitives: bool = False) -> Iterator:
    """Every SNLDesign in the top DB (non-primitive libraries by default)."""
    db = top_db()
    if db is None:
        return
    for lib in db.getLibraries():
        if not include_primitives and lib.isPrimitives():
            continue
        for design in lib.getSNLDesigns():
            yield design


def design_names(include_primitives: bool = False) -> List[str]:
    return [d.getName() for d in iter_designs(include_primitives)]


def find_design(name: str):
    for design in iter_designs(include_primitives=True):
        if design.getName() == name:
            return design
    return None


def suggest_designs(name: str, n: int = 8) -> List[str]:
    return difflib.get_close_matches(name, design_names(), n=n, cutoff=0.5)


# -- source locations --------------------------------------------------------

def source_loc(obj) -> Optional[Tuple[str, int, int, int, int]]:
    """Normalised (file, line, end_line, column, end_column), or None.

    The raw getSourceLoc tuple is (file, line, column, end_line, end_column);
    we reorder so the line span leads, matching SrcRange.
    """
    if obj is None or not hasattr(obj, "hasSourceLoc"):
        return None
    try:
        if not obj.hasSourceLoc():
            return None
        loc = obj.getSourceLoc()
    except Exception:
        return None
    if not loc:
        return None
    file, line, column, end_line, end_column = loc
    return (file, line, end_line, column, end_column)


def direction_str(direction) -> str:
    if direction == DIR_INPUT:
        return "input"
    if direction == DIR_OUTPUT:
        return "output"
    return str(direction).split(".")[-1].lower()


# -- hierarchical instance occurrences ---------------------------------------

@dataclass
class InstNode:
    """A hierarchical instance occurrence.

    `names` is the dotted path including the top name (("uart_top", "u_tx"));
    `design` is the model (the contents of this instance); `snl_instance` is the
    SNLInstance (None for the top); `snlpath` is the matching SNLPath used to
    build occurrences/equipotentials.
    """
    names: Tuple[str, ...]
    design: object
    snl_instance: object        # None for the top
    snlpath: object             # naja.SNLPath (empty for the top)

    @property
    def is_top(self) -> bool:
        return self.snl_instance is None

    @property
    def name(self) -> str:
        return self.names[-1]

    @property
    def path(self) -> str:
        return ".".join(self.names)

    @property
    def model_name(self) -> str:
        return self.design.getName()

    def is_leaf(self) -> bool:
        return self.design.isLeaf()

    def is_primitive(self) -> bool:
        return self.design.isPrimitive()

    def is_sequential(self) -> bool:
        return self.design.isSequential()

    def is_assign(self) -> bool:
        return self.design.isAssign()

    def child_count(self) -> int:
        return sum(1 for _ in self.design.getInstances())

    def source_loc(self):
        return source_loc(self.snl_instance if not self.is_top else self.design)


def top_node() -> InstNode:
    d = top_design()
    return InstNode((d.getName(),), d, None, naja.SNLPath())


def child_node(node: InstNode, name: str) -> Optional[InstNode]:
    inst = node.design.getInstance(name)
    if inst is None:
        return None
    return InstNode(node.names + (name,), inst.getModel(), inst,
                    naja.SNLPath(node.snlpath, inst))


def child_nodes(node: InstNode) -> Iterator[InstNode]:
    for inst in node.design.getInstances():
        yield InstNode(node.names + (inst.getName(),), inst.getModel(), inst,
                       naja.SNLPath(node.snlpath, inst))


def node_from_ids(id_list: List[int]) -> InstNode:
    """Build an InstNode from a top-rooted instance-id list."""
    design = top_design()
    names = [design.getName()]
    snlpath = naja.SNLPath()
    inst = None
    for i in id_list:
        inst = design.getInstanceByID(i)
        snlpath = naja.SNLPath(snlpath, inst)
        names.append(inst.getName())
        design = inst.getModel()
    return InstNode(tuple(names), design, inst, snlpath)


def path_str_from_ids(id_list: List[int]) -> str:
    design = top_design()
    parts = [design.getName()]
    for i in id_list:
        inst = design.getInstanceByID(i)
        if inst is None:
            break
        parts.append(inst.getName())
        design = inst.getModel()
    return ".".join(parts)


# -- terms / nets ------------------------------------------------------------

def is_bus(obj) -> bool:
    return type(obj).__name__ in _BUS_TYPES


def obj_bits(obj) -> list:
    """Bit-level components of a term/net (itself if already a bit/scalar)."""
    if is_bus(obj):
        try:
            return list(obj.getBits())
        except Exception:
            return [obj]
    return [obj]


def obj_width(obj) -> int:
    if is_bus(obj):
        try:
            return abs(obj.getMSB() - obj.getLSB()) + 1
        except Exception:
            return 1
    return 1


def net_bit(net, index: int):
    if is_bus(net):
        try:
            return net.getBit(index)
        except Exception:
            return None
    return None


def term_bit(term, index: int):
    if not is_bus(term):
        return None
    try:
        for b in term.getBits():
            if b.getBit() == index:
                return b
    except Exception:
        return None
    return None


# -- equipotentials ----------------------------------------------------------

def build_equipotential(kind: str, owner: InstNode, bit_obj):
    """Raw SNLEquipotential for a bit-level term or net in `owner`'s scope."""
    try:
        if kind == "term":
            if owner.is_top:
                return naja.SNLEquipotential(bit_obj)
            inst_term = owner.snl_instance.getInstTerm(bit_obj)
            occ = naja.SNLOccurrence(owner.snlpath.getHeadPath(), inst_term)
            return naja.SNLEquipotential(occ)
        # net bit: reach the equipotential through a connected component.
        inst_terms = list(bit_obj.getInstTerms())
        if inst_terms:
            occ = naja.SNLOccurrence(owner.snlpath, inst_terms[0])
            return naja.SNLEquipotential(occ)
        bit_terms = list(bit_obj.getBitTerms()) if hasattr(
            bit_obj, "getBitTerms") else []
        if bit_terms:
            if owner.is_top:
                return naja.SNLEquipotential(bit_terms[0])
            inst_term = owner.snl_instance.getInstTerm(bit_terms[0])
            occ = naja.SNLOccurrence(owner.snlpath.getHeadPath(), inst_term)
            return naja.SNLEquipotential(occ)
    except Exception:
        return None
    return None


def equi_leaf_occurrences(eq):
    """Yield (inst_term, id_list) for leaf-instance inst-term occurrences."""
    for occ in eq.getInstTermOccurrences():
        it = occ.getInstTerm()
        inst = it.getInstance()
        if not inst.getModel().isLeaf():
            continue
        ids = list(occ.getPath().getInstanceIDs())
        ids.append(inst.getID())
        yield it, ids


def equi_top_terms(eq):
    """Yield top-level design terms on the equipotential."""
    return eq.getTerms()


def equi_size(eq, cap: int) -> object:
    n = 0
    try:
        for _ in eq.getInstTermOccurrences():
            n += 1
            if n >= cap:
                return f"{cap}+"
    except Exception:
        return None
    return n
