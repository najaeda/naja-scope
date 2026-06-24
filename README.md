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
`trace_cone` (fanin/fanout combinational cone via naja `SNLLogicalCone`;
stop-at-flops/ports/black-boxes; counts + a `cross_hierarchy` summary naming the
frontier registers outside the cone root's subtree; lists bounded by
`max_frontier`).

Source & summaries: `get_source` (the SV lines that produced an object),
`get_module_card` (deterministic ports/counts/clock-reset card),
`get_stats` (per-model rollups).

Escape hatch: `query_python` — najaeda is the query language; recurring
patterns observed there get promoted to first-class tools.

Conventions (DESIGN.md §6): object references are hierarchical path strings;
every list is paginated (`limit`, `cursor`); responses carry
`src: "file:start-end"` where known; errors return structured suggestions.

## How source ranges work today

Since najaeda 0.7.2 every SNL object exposes its SystemVerilog origin directly
in Python through `getSourceLoc()` (naja #389/#390). naja-scope walks the raw
designs once and reads those locations straight into a sidecar index keyed by
`(model, kind, name)` — no Verilog dump, no attribute reparsing. Anonymous
lowered objects (FFs, gates) are first given stable derived names (`tx_o_dff`
for the FF driving `tx_o`), which is also what makes them addressable by path.
The index serializes alongside the naja-if snapshot, so source ranges survive a
snapshot reload (fixed in 0.7.4) with no re-elaboration.

## Scope

RTL/design questions on synthesizable SystemVerilog. Not a DV/testbench tool
(DESIGN.md §2 explains what is lost in lowering and why).

## Development

```sh
.venv/bin/python -m pytest tests/ -q
```

The structural/source/snapshot tests are green on najaeda 0.7.4+ (no xfails):
the upstream bugs once tracked — parameter-specialization merging and naja-if
SV-snapshot reload — are both fixed (see NAJAEDA_NOTES.md); the snapshot
round-trip (`tests/test_zz_snapshot.py`) is a normal passing test.

naja-scope targets **najaeda 0.7.7** — the Python `NLID` value class +
`NLUniverse.getObject(NLID)` that back its object-identity model
(`docs/identity-and-addressing.md`), plus the 0.7.6 gate combinatorial modeling
`trace_cone` needs. **0.7.7 is not on PyPI yet** — until it is, develop against
the local naja build at `/Users/xtof/WORK/naja3`, compiled for Homebrew Python
3.14 (it segfaults under a 3.11 interpreter), via the `.venv314` dev venv
(`mcp` + `pytest` installed) plus `PYTHONPATH`:

```sh
PYTHONPATH=/Users/xtof/WORK/naja3/build/test/najaeda ./.venv314/bin/python -m pytest -q
```

The CVA6 cross-hierarchy cone regression (`tests/test_zzz_cone_cva6.py`) is
slow and skips unless the `eval/.cache/cva6-small` snapshot is present.
