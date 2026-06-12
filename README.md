# naja-scope

Agent-facing query layer over [najaeda](https://github.com/najaeda/naja): an
MCP server whose tools let AI agents navigate elaborated SystemVerilog
designs — hierarchy, connectivity, drivers, cones, and source back-links —
without loading source code into context.

See [DESIGN.md](DESIGN.md) for architecture and scope;
[NAJAEDA_NOTES.md](NAJAEDA_NOTES.md) for upstream feature requests and bugs
found while building phase 1.

## Status: phase 1 (structural spine + source ranges)

The DESIGN.md §3 workflow works end to end:

```
resolve("uart_top.u_tx.tx_o")   → term descriptor with src range
get_drivers("uart_top.tx_o")    → { path: "uart_top.u_tx.tx_o_dff",
                                    model: "naja_dff", pin: "Q",
                                    src: "rtl/uart.sv:93-94" }
get_source("…tx_o_dff")         → the always_ff block, ~5 lines
```

Three calls, well under a thousand tokens, answer plus quotable source.

## Install / run

```sh
python3.11 -m venv --system-site-packages .venv   # najaeda from site-packages
.venv/bin/pip install -e .
.venv/bin/naja-scope-mcp                          # stdio MCP server
```

Register with Claude Code:

```sh
claude mcp add naja-scope -- /path/to/naja-scope/.venv/bin/naja-scope-mcp
```

## Tools

Lifecycle: `load_systemverilog` (files/flist/top), `load_verilog`,
`load_liberty`, `load_primitives`, `save_snapshot`, `load_snapshot`,
`reset_universe`, `status`.

Navigation: `resolve` (paths, bit selects, glob, did-you-mean),
`find` (design-wide glob, paginated), `get_hierarchy`.

Connectivity: `get_drivers`, `get_loads` (equipotential endpoints),
`trace_cone` (fanin/fanout, stop-at-flops, hard `max_nodes`).

Source & summaries: `get_source` (the SV lines that produced an object),
`get_module_card` (deterministic ports/counts/clock-reset card),
`get_stats` (per-model rollups).

Escape hatch: `query_python` — najaeda is the query language; recurring
patterns observed there get promoted to first-class tools.

Conventions (DESIGN.md §6): object references are hierarchical path strings;
every list is paginated (`limit`, `cursor`); responses carry
`src: "file:start-end"` where known; errors return structured suggestions.

## How source ranges work today

najaeda (as of 0.7.0) stamps `sv_src_*` on every netlist object but does not expose
them in Python. At index time naja-scope dumps attribute-annotated Verilog to
a temp file once and parses the ranges back into a sidecar keyed by
`(model, kind, name)` — public API only. Anonymous lowered objects (FFs,
gates) are first given stable derived names (`tx_o_dff` for the FF driving
`tx_o`), which is also what makes them addressable by path. When najaeda
exposes RTL infos directly, only `SourceIndex.build` changes.

## Scope

RTL/design questions on synthesizable SystemVerilog. Not a DV/testbench tool
(DESIGN.md §2 explains what is lost in lowering and why).

## Development

```sh
.venv/bin/python -m pytest tests/ -q
```

Two strict xfails track upstream najaeda bugs (specialization merging,
naja-if reload); they flip loudly when fixed upstream.
