#!/usr/bin/env bash
# examples/_core_v_mcu_fetch.sh — shared setup for the CORE-V-MCU demo
# scripts. Sourced by core_v_mcu_demo.sh and core_v_mcu_demo_agent.sh, not
# meant to be run directly.
#
# Clones CORE-V-MCU at a pinned commit (unless CORE_V_MCU_REPO_DIR already
# points at a checkout), runs `fusesoc --setup` to resolve its FuseSoC-
# managed vendored-IP tree into a file list (setup only, no simulator build —
# the multi-package layout needs fusesoc's bookkeeping, not naja-scope),
# normalizes that file list into a flist naja-scope's raw SystemVerilog
# frontend understands, and exports CORE_V_MCU_FLIST for the Python tour.

set -euo pipefail

CORE_V_MCU_REF="${CORE_V_MCU_REF:-4608714d3f6c2a2e67141b03a7aeb24ccdb3f73d}"
CORE_V_MCU_REPO_URL="${CORE_V_MCU_REPO_URL:-https://github.com/openhwgroup/core-v-mcu.git}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -z "${CORE_V_MCU_REPO_DIR:-}" ]; then
  CORE_V_MCU_REPO_DIR="$(mktemp -d)/core-v-mcu"
  echo "Cloning $CORE_V_MCU_REPO_URL @ $CORE_V_MCU_REF into $CORE_V_MCU_REPO_DIR ..." >&2
  git clone --quiet "$CORE_V_MCU_REPO_URL" "$CORE_V_MCU_REPO_DIR"
  git -C "$CORE_V_MCU_REPO_DIR" checkout --quiet "$CORE_V_MCU_REF"
else
  echo "Using existing CORE-V-MCU checkout: $CORE_V_MCU_REPO_DIR" >&2
fi

VC="$CORE_V_MCU_REPO_DIR/build/fusesoc/openhwgroup.org_systems_core-v-mcu_0/default-verilator/openhwgroup.org_systems_core-v-mcu_0.vc"

if [ ! -f "$VC" ]; then
  FUSESOC_VENV="$CORE_V_MCU_REPO_DIR/.fusesoc-venv"
  if [ ! -x "$FUSESOC_VENV/bin/fusesoc" ]; then
    echo "Setting up a venv for fusesoc ..." >&2
    python3 -m venv "$FUSESOC_VENV"
    "$FUSESOC_VENV/bin/pip" install --quiet --upgrade pip fusesoc
  fi
  echo "Running fusesoc --setup (file-list resolution only, no simulator build) ..." >&2
  "$FUSESOC_VENV/bin/fusesoc" --cores-root "$CORE_V_MCU_REPO_DIR" run \
    --target=default --tool=verilator --setup \
    --build-root "$CORE_V_MCU_REPO_DIR/build/fusesoc" \
    openhwgroup.org:systems:core-v-mcu
fi

CORE_V_MCU_FLIST="$CORE_V_MCU_REPO_DIR/build/fusesoc/core_v_mcu.flist"
if [ ! -f "$CORE_V_MCU_FLIST" ] || [ "$VC" -nt "$CORE_V_MCU_FLIST" ]; then
  python3 "$SCRIPT_DIR/_normalize_core_v_mcu_flist.py" "$VC" "$CORE_V_MCU_FLIST"
fi

export CORE_V_MCU_REPO_DIR CORE_V_MCU_FLIST
