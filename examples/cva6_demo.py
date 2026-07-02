#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""A scripted tour of naja-scope on CVA6 (github.com/openhwgroup/cva6), a
production RISC-V core -- MCP-only, no agent involved.

Unlike examples/walkthrough.py (a tiny bundled UART), CVA6 is a large
third-party repo and isn't checked into this repo. Run it via the wrapper,
which clones CVA6 at a pinned tag and sets the env vars naja-scope's flist
${VAR} substitution needs:

    ./examples/cva6_demo.sh

Or point CVA6_REPO_DIR at a checkout you already have (also set TARGET_CFG /
HPDCACHE_DIR if you're not using cv64a6_imafdc_sv39). This is the same
MCP-only tour that runs in CI (.github/workflows/cva6-demo.yml) as a
regression -- the asserts below pin the shape of the answers so the tour
can't silently drift from how the tools actually behave. See
examples/cva6_demo_agent.sh to point an actual agent (not this script) at the
same MCP server.
"""

import os
import sys

from naja_scope import api
from naja_scope.session import SESSION

CVA6_REPO_DIR = os.environ.get("CVA6_REPO_DIR")

if not CVA6_REPO_DIR:
    sys.exit(
        "CVA6_REPO_DIR is not set. Run ./examples/cva6_demo.sh (it clones "
        "CVA6 for you), or export CVA6_REPO_DIR to point at an existing "
        "checkout.")

# najaeda expands ${TARGET_CFG} / ${HPDCACHE_DIR} in the flist itself, so
# these must be real env vars, not just Python-side defaults.
os.environ.setdefault("TARGET_CFG", "cv64a6_imafdc_sv39")
TARGET_CFG = os.environ["TARGET_CFG"]
os.environ.setdefault(
    "HPDCACHE_DIR", os.path.join(CVA6_REPO_DIR, "core/cache_subsystem/hpdcache"))

FLIST = os.path.join(CVA6_REPO_DIR, "core/Flist.cva6")

DIV_STATE_Q = "cva6.ex_stage_i.i_mult.i_div.state_q"
DIV_STATE_D = "cva6.ex_stage_i.i_mult.i_div.state_d"
NOC_REQ_O = "cva6.noc_req_o"

# A whole-port fan-in cone on a wide top-level output (noc_req_o is 470 bits)
# is currently slow (multi-minute, measured on najaeda 0.7.9) because the
# cone is traced bit-by-bit. Kept here, not run by default, pending a najaeda
# speedup for wide-port cones; opt in with NAJA_SCOPE_DEMO_FULL_PORT_CONE=1.
RUN_FULL_PORT_CONE = os.environ.get("NAJA_SCOPE_DEMO_FULL_PORT_CONE") == "1"


def banner(title):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def main():
    banner(f"Load CVA6 (once) -- config {TARGET_CFG}")
    SESSION.reset()
    api.load_systemverilog(flist=FLIST, top="cva6")
    st = api.status()
    top = st["top"]
    print(f"loaded: top={top['name']}  direct children={top['children']}  "
          f"ports={top['terms']}")

    banner('Q: "Ignoring assign glue, what real submodules make up the top?"')
    h = api.get_hierarchy(depth=1, limit=100)
    root = h["root"]
    submodules = [c for c in root["children"] if not c.get("leaf")]
    print(f"  {root['assign_count']} assign-glue instances (not shown) + "
          f"{len(submodules)} real submodules:")
    for c in submodules:
        print(f"    - {c['name']}  [{c.get('model')}]")
    assert len(submodules) == 10, "expected the 10 cva6 pipeline submodules"
    assert root["assign_count"] > 1000, "expected thousands of assign-glue instances"

    banner('Q: "What drives the serial-divider FSM state register?"')
    drv = api.get_drivers(DIV_STATE_Q)
    leaf = drv["leaf_drivers"][0]
    print(f"  driver model : {leaf['model']}  (sequential={leaf['is_sequential']})")
    print(f"  source       : {leaf['src']}")
    assert "dffrn" in leaf["model"], "expected an async-reset flip-flop"
    assert "serdiv.sv" in leaf["src"], "expected the register in serdiv.sv"

    banner('Q: "Show me the RTL behind that register."')
    src = api.get_source(leaf["path"])
    print(f"  {src.get('src')}")
    for line in (src.get("text") or "").splitlines():
        print(f"    {line}")

    banner("Q: \"Does the divider's next-state logic depend on anything "
           "outside the EX stage?\" (fan-in cone, stop at flops)")
    cone = api.trace_cone(DIV_STATE_D, "fanin", max_frontier=200)
    frontier = cone["frontier"]
    print(f"  nodes in cone     : {cone['node_count']}")
    print(f"  register frontier : {frontier['flop_count']} flop(s), "
          f"{frontier['blackbox_count']} black box(es)")
    outside = cone["cross_hierarchy"]["outside_root_subtree"]
    print(f"  outside {cone['cross_hierarchy']['root_subtree']}: "
          f"{outside['count']} flop(s) in {sorted(outside['subtrees'])}")
    assert frontier["blackbox_count"] == 0, "cone should fully traverse combinational logic"
    assert outside["count"] > 0, "expected the cone to cross out of the EX stage"
    assert "cva6.csr_regfile_i" in outside["subtrees"], (
        "expected the divider's next state to be gated by CSR state")

    banner(f'Q: "What feeds the top-level output {NOC_REQ_O}?" '
           "(whole-port fan-in cone)")
    if RUN_FULL_PORT_CONE:
        cone = api.trace_cone(NOC_REQ_O, "fanin")
        frontier = cone["frontier"]
        print(f"  nodes in cone     : {cone['node_count']}")
        print(f"  register frontier : {frontier['flop_count']} flop(s), "
              f"{frontier['blackbox_count']} black box(es)")
    else:
        print("  skipped by default: a whole-port cone on this 470-bit port "
              "is slow today (multi-minute; the cone is traced bit-by-bit). "
              "Set NAJA_SCOPE_DEMO_FULL_PORT_CONE=1 to run it anyway once "
              "you're willing to wait, or after the next najaeda release "
              "(wide-port cone tracing is getting a speedup).")

    print("\nDone. A handful of small, exact calls answered structural, "
          "connectivity and cross-hierarchy questions on a real RISC-V core "
          "-- no RTL pasted into context.")


if __name__ == "__main__":
    main()
