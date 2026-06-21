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
    """Current session: loaded design summary, source-index state."""
    return api.status()


@_tool
def load_systemverilog(files: Optional[List[str]] = None,
                       flist: Optional[str] = None,
                       top: Optional[str] = None,
                       keep_assigns: bool = True) -> dict:
    """Elaborate SystemVerilog (files and/or an flist; optional top module).
    Names anonymous objects so everything is path-addressable."""
    return api.load_systemverilog(files, flist, top, keep_assigns)


@_tool
def load_verilog(files: List[str], keep_assigns: bool = True,
                 allow_unknown_designs: bool = False) -> dict:
    """Load gate-level/structural Verilog netlists."""
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
    """Persist the design + source index for fast reload (naja-if + sidecar)."""
    return api.save_snapshot(directory)


@_tool
def load_snapshot(directory: str) -> dict:
    """Reload a save_snapshot directory in seconds (no re-elaboration)."""
    return api.load_snapshot(directory)


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
                  limit: Optional[int] = None) -> dict:
    """Hierarchy tree under an instance (default top). depth<=5, children
    capped per level with truncation counts."""
    return api.get_hierarchy(path, depth, limit)


@_tool
def get_drivers(path: str, limit: Optional[int] = None) -> dict:
    """What drives this term/net: leaf drivers (FF/gate instances with pin,
    model, source ref) and top-level ports, through the equipotential."""
    return api.get_drivers(path, limit)


@_tool
def get_loads(path: str, limit: Optional[int] = None) -> dict:
    """What this term/net feeds: leaf readers and top-level ports."""
    return api.get_loads(path, limit)


@_tool
def trace_cone(path: str, direction: str, stop: str = "flops",
               max_nodes: int = 200, include_edges: bool = True) -> dict:
    """Trace the fanin/fanout cone of a term/net. direction: fanin|fanout.
    stop: flops|none. Returns nodes, edges, frontier, counts_by_model;
    hard-capped by max_nodes (<=1000) with truncation markers.
    frontier_summary groups the stop-at-flops frontier by top-level submodule
    and, under outside_root_subtree, names the frontier registers that live
    OUTSIDE the cone root's own subtree (the cross-hierarchy answer) — read it
    directly instead of re-deriving subtrees from the flat frontier list."""
    return api.trace_cone(path, direction, stop, max_nodes, include_edges)


@_tool
def get_source(path: str, context_lines: int = 3) -> dict:
    """SystemVerilog source lines that produced an object (FF instance ->
    its always_ff block). Returns file, range, text."""
    return api.get_source(path, context_lines)


@_tool
def get_module_card(module: str) -> dict:
    """Deterministic module summary: ports, instance counts by model,
    sequential count, clock/reset candidates (heuristic), source ref."""
    return api.get_module_card(module)


@_tool
def get_stats(path: Optional[str] = None, limit: Optional[int] = None,
              cursor: Optional[str] = None) -> dict:
    """Aggregated instance statistics per model under an instance
    (default top). Paginated."""
    return api.get_stats(path, limit, cursor)


@_tool
def query_python(code: str) -> dict:
    """Escape hatch: run Python against the live design ('naja' raw bindings,
    'snl' raw helpers, 'session', 'top' in scope). Read-only by convention;
    output capped."""
    return api.query_python(code)


def main():
    # naja's C++ logger writes to stdout, which would corrupt the JSON-RPC
    # stream. Route fd 1 to stderr for everyone, and give the MCP transport a
    # private duplicate of the real stdout.
    import io
    real_stdout = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = io.TextIOWrapper(os.fdopen(real_stdout, "wb"),
                                  encoding="utf-8", line_buffering=True)
    mcp.run()


if __name__ == "__main__":
    main()
