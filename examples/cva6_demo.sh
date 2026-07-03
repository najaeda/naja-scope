#!/usr/bin/env bash
# examples/cva6_demo.sh — clone CVA6 (or reuse an existing checkout) and run
# the naja-scope demo/regression against it (examples/cva6_demo.py).
#
# MCP-only, no agent involved — this is what CI runs
# (.github/workflows/cva6-demo.yml) and what a plain run gives you. See
# examples/cva6_demo_agent.sh to point an actual agent at the same MCP
# server afterward.
#
# Usage:
#   ./examples/cva6_demo.sh                            # clones into a scratch dir
#   CVA6_REPO_DIR=~/WORK/cva6 ./examples/cva6_demo.sh   # reuse an existing checkout
#
# Override via env: CVA6_REF (default v5.3.0), CVA6_REPO_URL, TARGET_CFG
# (default cv64a6_imafdc_sv39).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_cva6_fetch.sh
source "$SCRIPT_DIR/_cva6_fetch.sh"

python3 "$SCRIPT_DIR/cva6_demo.py"
