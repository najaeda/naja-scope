#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""A scripted tour of naja-scope on CORE-V-MCU
(github.com/openhwgroup/core-v-mcu), OpenHW Group's RISC-V microcontroller --
MCP-only, no agent involved.

Unlike examples/walkthrough.py (a tiny bundled UART), CORE-V-MCU is a large,
FuseSoC-managed third-party repo -- ~370 SystemVerilog files across a dozen
vendored IP trees (cv32e40p, PULP-platform AXI/TCDM, an eFPGA fabric, plus a
dozen undelivered technology hard macros) -- and isn't checked into this
repo. Run it via the wrapper, which clones CORE-V-MCU at a pinned commit,
runs `fusesoc --setup` to resolve its file list, and normalizes that into a
flist naja-scope can load:

    ./examples/core_v_mcu_demo.sh

Or point CORE_V_MCU_REPO_DIR at a checkout you already have (it still needs
the fusesoc-generated .vc under build/fusesoc/ -- see
examples/_core_v_mcu_fetch.sh). This is the same MCP-only tour that runs in
CI as a regression -- the asserts below pin the shape of the answers so the
tour can't silently drift from how the tools actually behave. See
examples/core_v_mcu_demo_agent.sh to point an actual agent (not this script)
at the same MCP server.
"""

import os
import sys

from naja_scope import api
from naja_scope.session import SESSION

CORE_V_MCU_FLIST = os.environ.get("CORE_V_MCU_FLIST")

if not CORE_V_MCU_FLIST:
    sys.exit(
        "CORE_V_MCU_FLIST is not set. Run ./examples/core_v_mcu_demo.sh (it "
        "clones CORE-V-MCU and runs fusesoc for you), or export "
        "CORE_V_MCU_REPO_DIR / CORE_V_MCU_FLIST directly (see "
        "examples/_core_v_mcu_fetch.sh).")

# The 12 undelivered technology hard macros the `default` fusesoc target
# leaves out (eFPGA fabric, SRAMs, PLL, clock-gate/mux/inverter cells) --
# matches naja core's own core_v_mcu regress case (expected_unknown_modules)
# exactly.
EXPECTED_BLACKBOXES = {
    "QL_eFPGA_ArcticPro2_32X32_GF_22_Arnold2", "a2_bootrom", "apb_pll",
    "cluster_clock_gating", "cluster_clock_inverter",
    "core_v_mcu_interleaved_ram", "core_v_mcu_private_ram",
    "cv32e40p_clock_gate", "pulp_clock_gating", "pulp_clock_inverter",
    "pulp_clock_mux2", "sram512x64",
}

# A pulp_sync_wedge CDC synchronizer buried in the eFPGA subsystem.
CDC_CLOCK_PIN = (
    "core_v_mcu.i_soc_domain.soc_peripherals_i.i_efpga_subsystem."
    "core_v_mcu_i_soc_domain_soc_peripherals_i_i_efpga_subsystem_"
    "event_wedge_edge_2_i_wedge_efpga.clk_i")


def banner(title):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def main():
    banner("Load CORE-V-MCU (once), blackboxing undelivered hard macros")
    SESSION.reset()
    api.load_systemverilog(flist=CORE_V_MCU_FLIST, top="core_v_mcu",
                           allow_unknown_designs=True)
    st = api.status()
    top = st["top"]
    print(f"loaded: top={top['name']}  direct children={top['children']}  "
          f"ports={top['terms']}")

    banner('Q: "What are the two direct children of the top module, and '
           'what do they instantiate?"')
    h = api.get_hierarchy(depth=1, limit=400)
    named = [c for c in h["root"]["children"] if not c.get("leaf")]
    for c in named:
        print(f"    - {c['name']}  [{c['model']}]")
    assert {c["model"] for c in named} == {"safe_domain", "soc_domain"}

    banner('Q: "How big is this design once elaborated?" (get_stats)')
    stats = api.get_stats()
    root = stats["models"][0]
    print(f"  flattened leaf gates    : {root['flat_leaves']:,}")
    print(f"  sequential instances    : {root['flat_sequential']:,}")
    print(f"  distinct model variants : {stats['total_models']}")
    assert root["flat_leaves"] > 700_000
    assert root["flat_sequential"] > 90_000

    banner('Q: "Which modules resolve as blackboxes (undelivered hard '
           'macros), with allow_unknown_designs=True?"')
    from najaeda import naja
    db = naja.NLUniverse.get().getTopDB()
    blackboxes = {
        d.getName() for lib in db.getLibraries() for d in lib.getSNLDesigns()
        if d.isBlackBox()
    }
    for name in sorted(blackboxes):
        print(f"    - {name}")
    assert blackboxes == EXPECTED_BLACKBOXES, (
        "blackbox set drifted from naja core's own core_v_mcu regress case")

    banner('Q: "A pulp_sync_wedge CDC cell is buried deep in the eFPGA '
           'subsystem. What clock domain is it actually on, and how far '
           'does that net reach?" (get_loads, equipotential across renamed '
           'ports)')
    loads = api.get_loads(CDC_CLOCK_PIN, limit=10)
    print(f"  pin queried                       : {loads['object']}")
    print(f"  net fan-out (equipotential_size)  : {loads['equipotential_size']}")
    by_model = {}
    for e in loads["leaf_loads"]:
        by_model[e["model"]] = by_model.get(e["model"], 0) + 1
    print(f"  sample of what shares this net (first {len(loads['leaf_loads'])}):")
    for model, n in sorted(by_model.items(), key=lambda kv: -kv[1]):
        print(f"    - {model}: {n}")
    assert loads["equipotential_size"] == 1563, (
        "clock net fan-out drifted -- re-check the CDC instance path above")

    print("\nDone. A handful of small, exact calls answered structural, "
          "connectivity, and cross-hierarchy questions on a real "
          "multi-vendor RISC-V SoC -- no RTL pasted into context, and no "
          "verilator pre-flattening: naja-scope reads the raw multi-file "
          "SystemVerilog directly.")


if __name__ == "__main__":
    main()
