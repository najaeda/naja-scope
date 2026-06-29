#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""A scripted tour of naja-scope on the bundled UART design.

This is the same sequence of questions an AI agent would ask through the MCP
tools, but driven directly from Python so you can run and read it end to end:

    python examples/walkthrough.py

It loads examples/uart.sv, then answers a handful of real design questions —
hierarchy, what drives a registered output, the source behind it, and a
fan-in logic cone — printing a compact result for each. The companion test
tests/test_examples_walkthrough.py asserts these same answers, so this tour
can't silently drift from how the tools actually behave.
"""

import os

from naja_scope import api
from naja_scope.session import SESSION

UART_SV = os.path.join(os.path.dirname(__file__), "uart.sv")


def banner(title):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def main():
    banner("Load the design (once)")
    SESSION.reset()
    SESSION.load_systemverilog([UART_SV])
    st = api.status()
    top = st["top"]
    print(f"loaded: top={top['name']}  direct children={top['children']}  "
          f"ports={top['terms']}")

    banner('Q: "What\'s the top-level hierarchy?"')
    h = api.get_hierarchy("uart_top", depth=1)
    print(_fmt_hierarchy(h["root"]))

    banner('Q: "What drives the registered output tx_o?"')
    drv = api.get_drivers("uart_top.tx_o")
    leaf = drv["leaf_drivers"][0]
    print(f"  driver model : {leaf['model']}  (sequential={leaf['is_sequential']})")
    print(f"  output pin   : {leaf['pin']}")
    print(f"  source       : {leaf['src']}")

    banner('Q: "Show me the RTL behind that flop."')
    src = api.get_source(leaf["path"])
    print(f"  {src.get('src')}")
    for line in (src.get("text") or "").splitlines():
        print(f"    {line}")

    banner('Q: "What feeds the FSM next-state logic (fan-in cone)?"')
    cone = api.trace_cone("uart_top.u_tx.state_n", "fanin")
    print(f"  nodes in cone     : {cone['node_count']}")
    print(f"  by kind           : {cone['counts_by_kind']}")
    print(f"  register frontier : {cone['frontier']['flop_count']} flop(s)")
    print(f"  black boxes       : {cone['frontier']['blackbox_count']} "
          "(0 == cone fully traversed combinational logic)")

    print("\nDone. Three to four small calls answered each question, "
          "no source dump required.")


def _fmt_hierarchy(node, indent=0):
    pad = "  " * indent
    name = node.get("name", "?")
    model = node.get("model")
    src = node.get("src")
    line = f"{pad}- {name}" + (f"  [{model}]" if model else "")
    if src:
        line += f"  ({src})"
    out = [line]
    # Only descend into real sub-instances, not the dozens of lowered gate
    # leaves — keep the tour readable.
    for child in node.get("children", []) or []:
        if not child.get("leaf"):
            out.append(_fmt_hierarchy(child, indent + 1))
    return "\n".join(out)


if __name__ == "__main__":
    main()
