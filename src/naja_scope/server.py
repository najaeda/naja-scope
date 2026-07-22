#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""naja-scope MCP server: navigate elaborated SystemVerilog designs.

Thin registration layer over naja_scope.api — keep docstrings tight, they are
the tool schemas agents pay tokens for on every session."""

from __future__ import annotations

import functools
import os
import sys
from typing import Any, Callable, Dict, List, Optional

# Allow using a local najaeda checkout without installing it.
_najaeda_src = os.getenv("NAJAEDA_SRC")
if _najaeda_src:
    sys.path.insert(0, _najaeda_src)

from mcp.server.fastmcp import FastMCP

from . import api
from .errors import ScopeError

mcp = FastMCP("naja-scope")


def _tool(fn: Callable) -> Callable:
    """Register fn as an MCP tool; ScopeErrors become structured responses."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs) -> Dict[str, Any]:
        try:
            return fn(*args, **kwargs)
        except ScopeError as e:
            return e.to_dict()

    return mcp.tool()(wrapper)


@_tool
def status() -> dict:
    """Current session: loaded design summary, and whether the intent
    layer is live (`intent_loaded`) / re-loadable (`intent_loadable`)."""
    return api.status()


@_tool
def load_systemverilog(files: Optional[List[str]] = None,
                       flist: Optional[str] = None,
                       top: Optional[str] = None,
                       keep_assigns: bool = True,
                       intent: bool = False) -> dict:
    """Elaborate SystemVerilog (files and/or an flist; optional top module).
    Anonymous lowered objects are addressable by #<id>.
    intent=True retains naja's in-engine SNL↔slang link for get_intent."""
    return api.load_systemverilog(files, flist, top, keep_assigns, intent)


@_tool
def load_verilog(files: List[str], keep_assigns: bool = True,
                 allow_unknown_designs: bool = False) -> dict:
    """Load gate-level/structural Verilog netlists. Pair with load_liberty (or
    load_primitives) so cells resolve to real models; allow_unknown_designs=True
    blackboxes any module still undefined instead of failing. Gate netlists carry
    no source info, so get_source/get_intent cannot answer for them."""
    return api.load_verilog(files, keep_assigns, allow_unknown_designs)


@_tool
def load_liberty(files: List[str]) -> dict:
    """Load Liberty cell libraries (defines primitives for gate netlists)."""
    return api.load_liberty(files)


@_tool
def load_primitives(name: Optional[str] = None,
                    file: Optional[str] = None) -> dict:
    """Load primitives: built-in by name ('xilinx'|'yosys') or a Python file
    defining load(db)."""
    return api.load_primitives(name, file)


@_tool
def save_snapshot(directory: str) -> dict:
    """Persist the design + source index for fast reload (naja-if + sidecar).
    Tied to the producing najaeda version — load_snapshot rejects a foreign one."""
    return api.save_snapshot(directory)


@_tool
def load_snapshot(directory: str, intent: bool = False) -> dict:
    """Reload a save_snapshot directory in seconds (no re-elaboration).
    intent=True also re-elaborates the warm intent layer from the flist saved in
    the snapshot (for get_intent)."""
    return api.load_snapshot(directory, intent)


@_tool
def reset_universe() -> dict:
    """Clear all loaded designs and session state."""
    return api.reset_universe()


@_tool
def resolve(path: str, kind: Optional[str] = None,
            limit: Optional[int] = None) -> dict:
    """Resolve a hierarchical path (e.g. 'top.u_uart.tx_o', bit selects and
    glob in last segment OK) to instance/term/net descriptors with source
    refs. On failure returns did-you-mean suggestions.
    kind: instance|term|net."""
    return api.resolve(path, kind, limit)


@_tool
def find(pattern: str, kind: str = "any", limit: Optional[int] = None,
         cursor: Optional[str] = None) -> dict:
    """Glob search names design-wide (pattern with '.' matches full paths).
    kind: instance|net|port|module|any. Paginated via cursor."""
    return api.find(pattern, kind, limit, cursor)


@_tool
def get_hierarchy(path: Optional[str] = None, depth: int = 1,
                  limit: Optional[int] = None,
                  cursor: Optional[str] = None) -> dict:
    """Hierarchy tree under an instance (default top). Lists only non-assign
    children (real submodules + leaf primitives); `assign` glue is reported as
    `assign_count`, not enumerated. Each child carries a `leaf` flag (submodule
    vs leaf primitive). depth<=5; the non-assign set is paginated at the root
    via limit/cursor (next_cursor/has_more), deeper levels via children_truncated."""
    return api.get_hierarchy(path, depth, limit, cursor)


@_tool
def get_drivers(path: str, limit: Optional[int] = None) -> dict:
    """What drives this term/net, through the equipotential: leaf drivers
    (FF/gate instances with pin, model, source ref) and top-level ports.
    Literal assign drivers include `constant` (0, 1, X, or Z); bus entries
    include the driven `bit`.
    Capped at limit (default 50, max 200) with a `truncated` flag; no cursor —
    raise limit to see more."""
    return api.get_drivers(path, limit)


@_tool
def get_loads(path: str, limit: Optional[int] = None) -> dict:
    """What this term/net feeds, through the equipotential: leaf readers
    (instances with pin, model, source ref) and top-level ports.
    Capped at limit (default 50, max 200) with a `truncated` flag; no cursor —
    raise limit to see more."""
    return api.get_loads(path, limit)


@_tool
def trace_cone(path: str, direction: str,
               max_frontier: int = 50) -> dict:
    """Trace the combinational fanin/fanout cone of a term/net via naja's
    LogicCone. direction: fanin|fanout. The cone crosses hierarchy and
    combinatorial arcs and always stops at flops, top ports, and opaque
    black-box cells. Returns node_count, counts_by_kind, counts_by_model, and a
    `frontier` of {flops, ports, blackboxes} with exact counts and lists capped
    at max_frontier (<=200) with a truncation marker.
    `cross_hierarchy` groups the flop frontier by top-level submodule and, under
    outside_root_subtree, names the frontier registers that live OUTSIDE the
    cone root's own subtree (the cross-hierarchy answer) — read it directly."""
    return api.trace_cone(path, direction, max_frontier)


@_tool
def get_source(path: str, context_lines: int = 3) -> dict:
    """SystemVerilog source lines that produced an object (FF instance ->
    its always_ff block). Returns file, range, text. Gate-level netlists carry
    no source info, so get_source cannot answer for them."""
    return api.get_source(path, context_lines)


@_tool
def get_module_card(module: str) -> dict:
    """Deterministic module summary: ports, instance counts by model,
    sequential count, source ref, plus clock/reset candidates — a name-based
    regex guess, not a structural result; verify before relying on it."""
    return api.get_module_card(module)


@_tool
def get_stats(path: Optional[str] = None, limit: Optional[int] = None,
              cursor: Optional[str] = None) -> dict:
    """Aggregated instance statistics per model under an instance
    (default top). Paginated."""
    return api.get_stats(path, limit, cursor)


@_tool
def get_intent(ref: str, want: str = "auto") -> dict:
    """Source-level INTENT a netlist erases in lowering (warm-only).
    Use when the answer is in the SystemVerilog *type/declaration*, not the
    flattened gates: enum/typedef state names + encodings (incl. PACKAGE
    typedefs whose members live in another file), and symbolic PARAMETER
    expressions (the formula behind a baked-in width).
    ref: a hierarchical path ('cva6.csr_regfile_i.priv_lvl_q'), a package member
    ('riscv::PLEN'), or an instance path for its parameters.
    want: auto | type | fsm_states | parameters. If the intent layer is not
    loaded, returns a note and you should fall back to get_source."""
    return api.get_intent(ref, want)


@_tool
def load_intent(flist: Optional[str] = None,
                files: Optional[List[str]] = None,
                top: Optional[str] = None) -> dict:
    """Make the warm intent layer available for get_intent (naja's in-engine
    SNL↔slang link). No-op if a load already retained it; otherwise re-elaborates
    WITH the link from the captured flist/files (pass them after a cold snapshot)."""
    return api.load_intent(flist, files, top)


# Opt-in: unsandboxed eval/exec in the server process, so it is not registered
# unless an operator sets NAJA_SCOPE_ENABLE_PYTHON. Costs no schema tokens when off.
if api.python_enabled():

    @_tool
    def query_python(code: str) -> dict:
        """Escape hatch: run Python against the live design ('naja' raw bindings,
        'snl' raw helpers, 'session', 'top' in scope). Prefer the typed tools
        above; use this only for queries they cannot express. Unsandboxed
        eval/exec in the server process — read-only by convention, not enforced.
        Output capped."""
        return api.query_python(code)


def main():
    # naja-scope defaults to a stdio MCP server: with no args it speaks JSON-RPC
    # on stdin/stdout and is meant to be launched by an MCP client. It can also
    # serve over HTTP (--transport streamable-http|sse) for clients that connect
    # to a remote MCP URL, e.g. ChatGPT custom connectors. Handle the
    # interactive flags people reflexively try so they get usage instead of a
    # stream of JSON-RPC parse errors.
    import argparse
    from importlib.metadata import PackageNotFoundError, version as _pkg_version

    try:
        _version = _pkg_version("naja-scope")
    except PackageNotFoundError:  # running from a source tree without install
        _version = "unknown"

    parser = argparse.ArgumentParser(
        prog="naja-scope-mcp",
        description="naja-scope MCP server: navigate elaborated SystemVerilog "
                    "and gate-level designs. Defaults to a stdio MCP server "
                    "(JSON-RPC over stdin/stdout), launched by an MCP client; "
                    "use --transport for an HTTP endpoint a remote client (e.g. "
                    "ChatGPT) can connect to.",
        epilog="Examples:\n"
               "  # stdio (Claude Code / Claude Desktop):\n"
               '  {"mcpServers": {"naja-scope": {"command": "naja-scope-mcp"}}}\n'
               "  # HTTP endpoint (ChatGPT connector / remote client):\n"
               "  naja-scope-mcp --transport streamable-http --host 127.0.0.1 --port 8000",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version",
                        version=f"naja-scope-mcp {_version}")
    parser.add_argument("--transport", choices=("stdio", "streamable-http", "sse"),
                        default="stdio",
                        help="MCP transport (default: stdio). Use "
                             "streamable-http or sse to serve over HTTP.")
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind host for HTTP transports (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000,
                        help="bind port for HTTP transports (default: 8000)")
    args = parser.parse_args()

    mcp.settings.host = args.host
    mcp.settings.port = args.port

    # naja's C++ logger writes to stdout, which would corrupt the stdio JSON-RPC
    # stream. Route fd 1 to stderr for everyone (harmless for HTTP, where the
    # protocol does not use stdout), and give the transport a private duplicate
    # of the real stdout.
    import io
    real_stdout = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = io.TextIOWrapper(os.fdopen(real_stdout, "wb"),
                                  encoding="utf-8", line_buffering=True)
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
