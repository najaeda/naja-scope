#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""naja-scope MCP server: navigate elaborated SystemVerilog designs.

Thin registration layer over naja_scope.api — keep docstrings tight, they are
the tool schemas agents pay tokens for on every session."""

from __future__ import annotations

import functools
import os
import sys
from typing import Annotated, Any, Callable, Dict, List, Literal, Optional

# Allow using a local najaeda checkout without installing it.
_najaeda_src = os.getenv("NAJAEDA_SRC")
if _najaeda_src:
    sys.path.insert(0, _najaeda_src)

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from . import api
from .errors import ScopeError

mcp = FastMCP("naja-scope")


# MCP annotations complement the descriptions with machine-readable safety
# hints. "Read only" refers to the design and filesystem; query tools may still
# populate ordinary in-process caches.
READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
SESSION_MUTATION = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
SESSION_REPLACEMENT = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=False,
)
FILESYSTEM_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
    openWorldHint=False,
)
SESSION_RESET = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
    openWorldHint=False,
)
ARBITRARY_PYTHON = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=True,
)


def _tool(*, annotations: ToolAnnotations) -> Callable:
    """Register fn as an MCP tool; ScopeErrors become structured responses."""

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> Dict[str, Any]:
            try:
                return fn(*args, **kwargs)
            except ScopeError as e:
                return e.to_dict()

        return mcp.tool(annotations=annotations)(wrapper)

    return decorator


@_tool(annotations=READ_ONLY)
def status() -> dict:
    """Inspect the current in-memory session without changing it. Use this
    before design queries to confirm a design is loaded and whether get_intent
    is live (`intent_loaded`) or can be reloaded (`intent_loadable`). Returns
    `loaded` and, when available, the top summary and loaded source files."""
    return api.status()


@_tool(annotations=SESSION_MUTATION)
def load_systemverilog(
    files: Annotated[
        Optional[List[str]],
        Field(description="Local SystemVerilog source file paths; optional "
                          "when flist is provided."),
    ] = None,
    flist: Annotated[
        Optional[str],
        Field(description="Path to a simulator-style file list; optional "
                          "when files are provided."),
    ] = None,
    top: Annotated[
        Optional[str],
        Field(description="Top module name; omit to use najaeda's inferred top."),
    ] = None,
    keep_assigns: Annotated[
        bool,
        Field(description="Preserve continuous assignments as explicit lowered objects."),
    ] = True,
    intent: Annotated[
        bool,
        Field(description="Retain the live SNL-to-slang link required by "
                          "get_intent; uses more memory."),
    ] = False,
    defines: Annotated[
        Optional[List[str]],
        Field(description='Preprocessor definitions as "NAME" or "NAME=VALUE" entries.'),
    ] = None,
    allow_unknown_designs: Annotated[
        bool,
        Field(description="Black-box unresolved module definitions instead "
                          "of failing elaboration."),
    ] = False,
) -> dict:
    """Elaborate local SystemVerilog sources into the active design session.
    Use this for RTL; use load_verilog with load_liberty/load_primitives for a
    structural gate netlist. Requires at least `files` or `flist` and changes
    the in-memory design session.
    Anonymous lowered objects are addressable by #<id>. defines are
    preprocessor -D entries ("NAME" or "NAME=VALUE"). allow_unknown_designs=True
    blackboxes any module still undefined instead of failing (e.g. undelivered
    hard macros in a partly-open-source design). intent=True retains naja's
    in-engine SNL↔slang link for get_intent."""
    return api.load_systemverilog(files, flist, top, keep_assigns, intent,
                                  defines, allow_unknown_designs)


@_tool(annotations=SESSION_MUTATION)
def load_verilog(
    files: Annotated[
        List[str],
        Field(description="One or more local structural Verilog netlist paths."),
    ],
    keep_assigns: Annotated[
        bool,
        Field(description="Preserve continuous assignments as explicit objects."),
    ] = True,
    allow_unknown_designs: Annotated[
        bool,
        Field(description="Black-box unresolved cell/module definitions instead of failing."),
    ] = False,
) -> dict:
    """Load local gate-level or structural Verilog into the active session.
    First call load_liberty for Liberty cells or load_primitives for built-ins;
    use load_systemverilog instead for RTL elaboration. Unknown modules fail
    unless `allow_unknown_designs` is true. Gate netlists carry no source info,
    so get_source/get_intent cannot answer for them."""
    return api.load_verilog(files, keep_assigns, allow_unknown_designs)


@_tool(annotations=SESSION_MUTATION)
def load_liberty(
    files: Annotated[
        List[str],
        Field(description="One or more local Liberty .lib file paths."),
    ],
) -> dict:
    """Register standard-cell models from local Liberty `.lib` files in the
    active session. Use this before load_verilog when a gate netlist instantiates
    those cells; use load_primitives instead for the built-in Xilinx or Yosys
    model sets. This changes session state and returns `{"ok": true}`."""
    return api.load_liberty(files)


@_tool(annotations=ARBITRARY_PYTHON)
def load_primitives(
    name: Annotated[
        Optional[Literal["xilinx", "yosys"]],
        Field(description="Built-in primitive set to register; when set, file is ignored."),
    ] = None,
    file: Annotated[
        Optional[str],
        Field(description="Local Python file defining load(db); used only when name is omitted."),
    ] = None,
) -> dict:
    """Register primitive models in the active session from either a built-in
    `name` (`xilinx` or `yosys`) or one local Python `file` defining `load(db)`.
    Provide one source; `name` takes precedence when both are set. A custom file
    executes unsandboxed Python in the server process, so only use trusted code.
    Use load_liberty instead for standard-cell `.lib` files. Returns
    `{"ok": true}`."""
    return api.load_primitives(name, file)


@_tool(annotations=FILESYSTEM_WRITE)
def save_snapshot(
    directory: Annotated[
        str,
        Field(description="Local destination directory for naja-if and metadata files."),
    ],
) -> dict:
    """Write the active design and source metadata to a local directory for
    fast reload. Use after loading a design; load_snapshot reads the result.
    Existing snapshot files in the directory may be overwritten. Snapshots are
    tied to their producing najaeda version, and returns include the saved path."""
    return api.save_snapshot(directory)


@_tool(annotations=SESSION_MUTATION)
def load_snapshot(
    directory: Annotated[
        str,
        Field(description="Local directory previously created by save_snapshot."),
    ],
    intent: Annotated[
        bool,
        Field(description="Also rebuild the warm intent layer from saved elaboration inputs."),
    ] = False,
) -> dict:
    """Load a compatible save_snapshot directory into the active session in
    seconds instead of re-elaborating. Use load_systemverilog/load_verilog when
    no compatible snapshot exists. The directory must match this najaeda version.
    intent=True also re-elaborates the warm intent layer from the flist saved in
    the snapshot (for get_intent)."""
    return api.load_snapshot(directory, intent)


@_tool(annotations=SESSION_RESET)
def reset_universe() -> dict:
    """Discard the active design and all in-memory session state. Use before
    starting an unrelated design; do not use merely to inspect status. This is
    destructive to the current session but does not delete source or snapshots.
    Repeating it is safe and returns `{"ok": true}`."""
    return api.reset_universe()


@_tool(annotations=READ_ONLY)
def resolve(
    path: Annotated[
        str,
        Field(description="Hierarchical object path; the final segment may "
                          "be a glob or bit select."),
    ],
    kind: Annotated[
        Optional[Literal["instance", "term", "net"]],
        Field(description="Optional object-kind filter for otherwise ambiguous paths."),
    ] = None,
    limit: Annotated[
        Optional[int],
        Field(description="Maximum matches to return; defaults to 20 and is capped at 200."),
    ] = None,
) -> dict:
    """Resolve a known hierarchical object path to instance, term, or net
    descriptors with source references. The final segment accepts a glob and
    bit selects (for example `top.u_uart.tx_o[0]`). Use find when the path is
    unknown; use get_hierarchy to browse children. This read-only query requires
    a loaded design and returns did-you-mean suggestions on failure."""
    return api.resolve(path, kind, limit)


@_tool(annotations=READ_ONLY)
def find(
    pattern: Annotated[
        str,
        Field(description="Case-sensitive glob; include a dot to match full hierarchical paths."),
    ],
    kind: Annotated[
        Literal["instance", "net", "port", "module", "any"],
        Field(description="Restrict results to one design-object kind, or any."),
    ] = "any",
    limit: Annotated[
        Optional[int],
        Field(description="Page size; defaults to 50 and is capped at 200."),
    ] = None,
    cursor: Annotated[
        Optional[str],
        Field(description="Opaque next_cursor from the previous response; "
                          "omit for the first page."),
    ] = None,
) -> dict:
    """Search case-sensitive object names across the loaded design with a glob.
    Use this when an exact path is unknown; use resolve once a path is known or
    get_hierarchy to browse structure. A dot in `pattern` switches matching to
    full hierarchical paths. Returns typed descriptors in `matches` plus
    `count`, `has_more`, and an opaque `next_cursor` for pagination."""
    return api.find(pattern, kind, limit, cursor)


@_tool(annotations=READ_ONLY)
def get_hierarchy(
    path: Annotated[
        Optional[str],
        Field(description="Hierarchical instance path; omit to start at the top instance."),
    ] = None,
    depth: Annotated[
        int,
        Field(description="Tree depth from 1 through 5; out-of-range values are clamped."),
    ] = 1,
    limit: Annotated[
        Optional[int],
        Field(description="Maximum non-assign children per level; root default 20, maximum 100."),
    ] = None,
    cursor: Annotated[
        Optional[str],
        Field(description="Opaque root-level next_cursor from a previous response."),
    ] = None,
) -> dict:
    """Browse the instance tree below `path` (or the top instance). Use this
    for structural children; use find for design-wide name search or get_stats
    for aggregate model counts. Lists only non-assign
    children (real submodules + leaf primitives); `assign` glue is reported as
    `assign_count`, not enumerated. Each child carries a `leaf` flag (submodule
    vs leaf primitive). depth<=5; the non-assign set is paginated at the root
    via limit/cursor (next_cursor/has_more), deeper levels via children_truncated."""
    return api.get_hierarchy(path, depth, limit, cursor)


@_tool(annotations=READ_ONLY)
def get_drivers(
    path: Annotated[
        str,
        Field(description="Exact hierarchical path to a term or net in the loaded design."),
    ],
    limit: Annotated[
        Optional[int],
        Field(description="Maximum endpoint entries; defaults to 50 and is capped at 200."),
    ] = None,
) -> dict:
    """List the immediate upstream endpoints that drive a term or net across
    hierarchy. Use this for direct sources; use get_loads for downstream readers
    or trace_cone for the transitive combinational fanin. Returns leaf drivers
    (FF/gate instances with pin, model, source ref) and top-level ports.
    Lowered assign glue is traversed rather than reported as an endpoint.
    Literal assign drivers include `constant` (0, 1, X, or Z); bus entries
    include the driven `bit`.
    Capped at limit (default 50, max 200) with a `truncated` flag; no cursor —
    raise limit to see more."""
    return api.get_drivers(path, limit)


@_tool(annotations=READ_ONLY)
def get_loads(
    path: Annotated[
        str,
        Field(description="Exact hierarchical path to a term or net in the loaded design."),
    ],
    limit: Annotated[
        Optional[int],
        Field(description="Maximum endpoint entries; defaults to 50 and is capped at 200."),
    ] = None,
) -> dict:
    """List the immediate downstream endpoints that consume a term or net
    across hierarchy. Use this for direct readers; use get_drivers for upstream
    sources or trace_cone for the transitive combinational fanout. Returns leaf
    readers
    (instances with pin, model, source ref) and top-level ports. Lowered assign
    glue is traversed rather than reported as an endpoint.
    Capped at limit (default 50, max 200) with a `truncated` flag; no cursor —
    raise limit to see more."""
    return api.get_loads(path, limit)


@_tool(annotations=READ_ONLY)
def trace_cone(
    path: Annotated[
        str,
        Field(description="Exact hierarchical path to the cone's root term or net."),
    ],
    direction: Annotated[
        Literal["fanin", "fanout"],
        Field(description="Traverse upstream fanin or downstream fanout logic."),
    ],
    max_frontier: Annotated[
        int,
        Field(description="Maximum listed endpoints per frontier kind; clamped to 1..200."),
    ] = 50,
) -> dict:
    """Trace the combinational fanin/fanout cone of a term/net via naja's
    LogicCone. Use this for transitive logic reachability; use get_drivers or
    get_loads for only immediate endpoints. direction: fanin|fanout. The cone
    crosses hierarchy and
    combinatorial arcs and always stops at flops, top ports, and opaque
    black-box cells. Returns node_count, counts_by_kind, counts_by_model, and a
    `frontier` of {flops, ports, blackboxes} with exact counts and lists capped
    at max_frontier (<=200) with a truncation marker.
    `cross_hierarchy` groups the flop frontier by top-level submodule and, under
    outside_root_subtree, names the frontier registers that live OUTSIDE the
    cone root's own subtree (the cross-hierarchy answer) — read it directly."""
    return api.trace_cone(path, direction, max_frontier)


@_tool(annotations=READ_ONLY)
def get_source(
    path: Annotated[
        str,
        Field(description="Exact hierarchical path to an object from a SystemVerilog load."),
    ],
    context_lines: Annotated[
        int,
        Field(description="Extra lines before and after the source range; clamped to 0..20."),
    ] = 3,
) -> dict:
    """Read the bounded SystemVerilog source excerpt that produced an object
    (for example, an FF instance maps to its `always_ff` block). Use after
    load_systemverilog when exact source text is needed; use get_intent for
    typedef/enum/parameter semantics and do not use for gate-level Verilog.
    Returns object, file, start/end range, text, and truncation status without
    modifying files; missing paths and source ranges return structured errors."""
    return api.get_source(path, context_lines)


@_tool(annotations=READ_ONLY)
def get_module_card(
    module: Annotated[
        str,
        Field(description="Elaborated module/model name, not an instance path."),
    ],
) -> dict:
    """Deterministic module summary: ports, instance counts by model,
    sequential count, source ref, plus clock/reset candidates — a name-based
    regex guess, not a structural result; verify before relying on it. Use this
    for one model's interface; use get_stats for counts below an instance."""
    return api.get_module_card(module)


@_tool(annotations=READ_ONLY)
def get_stats(
    path: Annotated[
        Optional[str],
        Field(description="Hierarchical instance path; omit to summarize the top design."),
    ] = None,
    limit: Annotated[
        Optional[int],
        Field(description="Models per page; defaults to 25 and is capped at 200."),
    ] = None,
    cursor: Annotated[
        Optional[str],
        Field(description="Opaque next_cursor from the previous response; "
                          "omit for the first page."),
    ] = None,
) -> dict:
    """Summarize instance population by model below `path` or the top design.
    Use this for aggregate leaf/sequential/model counts; use get_hierarchy for
    actual child instances or get_module_card for one model's ports. This
    read-only query requires a loaded design. Returns `root_model`, flat totals,
    a paginated `models` list, `total_models`, `has_more`, and `next_cursor`."""
    return api.get_stats(path, limit, cursor)


@_tool(annotations=READ_ONLY)
def get_intent(
    ref: Annotated[
        str,
        Field(description="Hierarchical object/instance path or package "
                          "member such as pkg::NAME."),
    ],
    want: Annotated[
        Literal["auto", "type", "fsm_states", "parameters"],
        Field(description="Intent fact to retrieve; auto selects from the reference."),
    ] = "auto",
) -> dict:
    """Retrieve source-level intent that netlist lowering erases (warm-only).
    Use when the answer is in the SystemVerilog *type/declaration*, not the
    flattened gates: enum/typedef state names + encodings (incl. PACKAGE
    typedefs whose members live in another file), and symbolic PARAMETER
    expressions (the formula behind a baked-in width).
    ref: a hierarchical path ('cva6.csr_regfile_i.priv_lvl_q'), a package member
    ('riscv::PLEN'), or an instance path for its parameters.
    want: auto | type | fsm_states | parameters. If the intent layer is not
    loaded, returns a note and you should fall back to get_source."""
    return api.get_intent(ref, want)


@_tool(annotations=SESSION_REPLACEMENT)
def load_intent(
    flist: Annotated[
        Optional[str],
        Field(description="SystemVerilog file-list path; omit to reuse captured load inputs."),
    ] = None,
    files: Annotated[
        Optional[List[str]],
        Field(description="SystemVerilog source paths; omit to reuse captured load inputs."),
    ] = None,
    top: Annotated[
        Optional[str],
        Field(description="Top module name; omit to reuse the captured or inferred top."),
    ] = None,
) -> dict:
    """Make the warm source-intent layer available for get_intent. Use after a
    SystemVerilog load that did not retain intent; do not call for gate-level
    Verilog, and prefer `load_systemverilog(intent=True)` on the initial load.
    This is a no-op when the link is already live; otherwise it replaces the
    active universe by re-elaborating from explicit or captured `flist`/`files`.
    Returns `intent_loaded`; missing inputs produce a structured error."""
    return api.load_intent(flist, files, top)


# Opt-in: unsandboxed eval/exec in the server process, so it is not registered
# unless an operator sets NAJA_SCOPE_ENABLE_PYTHON. Costs no schema tokens when off.
if api.python_enabled():

    @_tool(annotations=ARBITRARY_PYTHON)
    def query_python(
        code: Annotated[
            str,
            Field(description="Python expression or statements to execute "
                              "in the live server process."),
        ],
    ) -> dict:
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
