#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""A scripted tour of naja-scope on a GATE-LEVEL (post-synthesis) netlist.

naja-scope is not only for RTL: point it at a structural Verilog netlist plus
the Liberty library that defines its standard cells, and you can navigate the
gates the same way — hierarchy, per-cell counts, what drives each flop, and
logic cones that stop at the sequential cells.

    python examples/gate_level.py

It loads examples/stdcells.lib (the cell library) then examples/counter2.v (a
2-bit counter built from INV / XOR2 / DFF cells). The companion test
tests/test_examples_gate_level.py asserts these same answers, so this tour
can't silently drift from how the tools actually behave.

Note: a gate netlist carries no SystemVerilog source info, so get_source has
nothing to point at here — gate-level is about structure and connectivity.
"""

import os

from naja_scope import api
from naja_scope.session import SESSION

HERE = os.path.dirname(__file__)
LIB = os.path.join(HERE, "stdcells.lib")
NETLIST = os.path.join(HERE, "counter2.v")


def banner(title):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def main():
    banner("Load the cell library, then the gate netlist")
    SESSION.reset()
    api.load_liberty([LIB])          # 1. cells first
    api.load_verilog([NETLIST])      # 2. then the structural netlist
    top = api.status()["top"]
    print(f"loaded: top={top['name']}  cells={top['children']}  ports={top['terms']}")

    banner('Q: "What cells is this netlist built from?"')
    card = api.get_module_card("counter2")
    print(f"  ports : {[p['name'] for p in card['ports']]}")
    print(f"  cells : {card['counts']['by_model']}")

    banner('Q: "What drives output q1?"')
    leaf = api.get_drivers("counter2.q1")["leaf_drivers"][0]
    print(f"  cell  : {leaf['path']}  model={leaf['model']}  pin={leaf['pin']}")

    banner('Q: "What feeds the q1 flop\'s D input (fan-in cone)?"')
    cone = api.trace_cone("counter2.u_ff1.D", "fanin")
    fr = cone["frontier"]
    print(f"  nodes in cone     : {cone['node_count']}")
    print(f"  by kind           : {cone['counts_by_kind']}")
    # The DFFs are opaque library cells, so the cone stops at them — they form
    # the cell (black-box) frontier rather than a lowered-flop frontier.
    print(f"  stops at cells    : {[b['path'] for b in fr['blackboxes']]}")

    print("\nDone. Same navigation as RTL — on a synthesized gate netlist.")


if __name__ == "__main__":
    main()
