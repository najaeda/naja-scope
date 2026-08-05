#!/usr/bin/env bash
# examples/core_v_mcu_demo_agent.sh — OPTIONAL: point an actual agent at the
# CORE-V-MCU MCP server, instead of the deterministic Python tour
# (core_v_mcu_demo.py).
#
# examples/core_v_mcu_demo.sh / core_v_mcu_demo.py are MCP-only, no agent --
# that's the deterministic regression. This script is the other half: it
# starts naja-scope-mcp against the same CORE-V-MCU checkout and drives it
# with an agent CLI, so you can see what an AI assistant actually does with
# the tools. Never invoked by CI (costs tokens / API calls, non-deterministic).
#
# Default agent: Claude Code (`claude -p`). Plug in a different one with
# AGENT_CMD -- it's invoked as `$AGENT_CMD "<prompt>" --mcp-config <path>
# --strict-mcp-config --allowedTools mcp__naja-scope`; adjust the flags in
# this script if your agent CLI's interface differs.
#
# Usage:
#   ./examples/core_v_mcu_demo_agent.sh
#   CORE_V_MCU_REPO_DIR=~/WORK/core-v-mcu ./examples/core_v_mcu_demo_agent.sh
#   AGENT_CMD='my-agent-cli -p' ./examples/core_v_mcu_demo_agent.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_core_v_mcu_fetch.sh
source "$SCRIPT_DIR/_core_v_mcu_fetch.sh"

NAJA_SCOPE_MCP="${NAJA_SCOPE_MCP:-$(command -v naja-scope-mcp || true)}"
[ -n "$NAJA_SCOPE_MCP" ] || {
  echo "ERROR: naja-scope-mcp not found on PATH (pip install -e . / pip install naja-scope)"
  exit 1
}

MCP_CONFIG="$(mktemp)"
cat > "$MCP_CONFIG" <<JSON
{"mcpServers":{"naja-scope":{"command":"$NAJA_SCOPE_MCP"}}}
JSON

PROMPT="Use the naja-scope MCP tools ONLY (no file reading). \
1) Call load_systemverilog with flist='$CORE_V_MCU_FLIST', top='core_v_mcu', \
allow_unknown_designs=true (12 undelivered technology hard macros get \
blackboxed instead of failing the load; first load takes about 10s). \
2) Find an instance whose path matches *event_wedge*efpga* (a pulp_sync_wedge \
CDC synchronizer buried in the eFPGA subsystem) and call get_loads on its \
clk_i pin. Report the equipotential_size and which other subsystems (by \
instance path prefix) share that net. \
3) Call get_stats at the root and report the flattened gate and flip-flop \
counts. \
End with a single line 'ANSWER: ...'."

AGENT_CMD="${AGENT_CMD:-claude -p}"
echo "Running: $AGENT_CMD <prompt> --mcp-config $MCP_CONFIG --allowedTools mcp__naja-scope"
# shellcheck disable=SC2086
$AGENT_CMD "$PROMPT" --mcp-config "$MCP_CONFIG" --strict-mcp-config --allowedTools "mcp__naja-scope"
