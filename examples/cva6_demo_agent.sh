#!/usr/bin/env bash
# examples/cva6_demo_agent.sh — OPTIONAL: point an actual agent at the CVA6
# MCP server, instead of the deterministic Python tour (cva6_demo.py).
#
# examples/cva6_demo.sh / cva6_demo.py are MCP-only, no agent — that's what
# CI runs (.github/workflows/cva6-demo.yml) and what a plain run gives you.
# This script is the other half: it starts naja-scope-mcp against the same
# CVA6 checkout and drives it with an agent CLI, so you can see what an AI
# assistant actually does with the tools. Never invoked by CI (costs tokens /
# API calls, non-deterministic).
#
# Default agent: Claude Code (`claude -p`). Plug in a different one with
# AGENT_CMD — it's invoked as `$AGENT_CMD "<prompt>" --mcp-config <path>
# --strict-mcp-config --allowedTools mcp__naja-scope`; adjust the flags in
# this script if your agent CLI's interface differs.
#
# Usage:
#   ./examples/cva6_demo_agent.sh
#   CVA6_REPO_DIR=~/WORK/cva6 ./examples/cva6_demo_agent.sh
#   AGENT_CMD='my-agent-cli -p' ./examples/cva6_demo_agent.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_cva6_fetch.sh
source "$SCRIPT_DIR/_cva6_fetch.sh"

FLIST="$CVA6_REPO_DIR/core/Flist.cva6"
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
1) Call load_systemverilog with flist='$FLIST' and top='cva6' ($TARGET_CFG; \
first load takes under a minute). \
2) Call get_hierarchy and list the real submodules (ignore assign glue). \
3) Call get_drivers on cva6.ex_stage_i.i_mult.i_div.state_q and report the driver. \
4) Call trace_cone(path='cva6.ex_stage_i.i_mult.i_div.state_d', direction='fanin') \
and report whether the frontier reaches registers outside the EX stage, naming \
one such register or module. \
End with a single line 'ANSWER: ...'."

AGENT_CMD="${AGENT_CMD:-claude -p}"
echo "Running: $AGENT_CMD <prompt> --mcp-config $MCP_CONFIG --allowedTools mcp__naja-scope"
# shellcheck disable=SC2086
$AGENT_CMD "$PROMPT" --mcp-config "$MCP_CONFIG" --strict-mcp-config --allowedTools "mcp__naja-scope"
