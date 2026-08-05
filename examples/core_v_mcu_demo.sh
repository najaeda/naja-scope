#!/usr/bin/env bash
# examples/core_v_mcu_demo.sh — clone CORE-V-MCU (or reuse an existing
# checkout), resolve its file list via fusesoc, and run the naja-scope
# demo/regression against it (examples/core_v_mcu_demo.py).
#
# MCP-only, no agent involved. See examples/core_v_mcu_demo_agent.sh to point
# an actual agent at the same MCP server afterward.
#
# Usage:
#   ./examples/core_v_mcu_demo.sh                                        # clones into a scratch dir
#   CORE_V_MCU_REPO_DIR=~/WORK/core-v-mcu ./examples/core_v_mcu_demo.sh   # reuse an existing checkout
#
# Override via env: CORE_V_MCU_REF (pinned commit), CORE_V_MCU_REPO_URL.
# Needs `fusesoc` to resolve CORE-V-MCU's FuseSoC-managed file list -- the
# fetch script below sets up its own venv for that, nothing to install by
# hand.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_core_v_mcu_fetch.sh
source "$SCRIPT_DIR/_core_v_mcu_fetch.sh"

python3 "$SCRIPT_DIR/core_v_mcu_demo.py"
