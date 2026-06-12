# najaeda feedback from naja-scope (phase 1)

Findings while building the MCP layer, first against najaeda 0.5.2 (the
version installed when work started), retested against 0.7.0 (current PyPI,
now the project floor). Per project rules, missing capabilities become
najaeda feature requests — no private hooks. Each item has a repro against
`tests/fixtures/uart.sv` unless noted.

Notable 0.7.0 change: sequential lowering now produces word-level FF
primitives (`naja_dffrn__w8` — one instance per register, not per bit),
which shrinks driver/load/cone answers and is strictly better for the agent
use case.

## Feature requests

1. **Expose `sv_src_*` RTL infos through the Python bindings** (the DESIGN.md
   week-1 item). Today the only egress is
   `dump_verilog(dumpRTLInfosAsAttributes=True)`; naja-scope works around it
   by dumping annotated Verilog at index time and parsing the attributes back
   (`src/naja_scope/source_index.py`). A `get_rtl_info()` /
   `get_attributes()`-visible form on SNL objects removes the dump+parse.
2. **`sv_symbol_path` RTL info** (slang hierarchical path) stamped at lowering
   time alongside `sv_src_*` — the persistent join key phase 2 needs to
   re-bind a live slang AST to a snapshot-loaded SNL (DESIGN.md prep hook 1).
3. **Stable names for lowered objects at construction time** — primitive
   instances created by sequential/comb lowering are unnamed; the dumper
   invents `instance_N` names. naja-scope names them post-load
   (`src/naja_scope/naming.py`, derived from the driven net, e.g.
   `tx_o_dff`); doing this during lowering would make names canonical
   everywhere.

## Bugs found

1. **Parameter specializations merged** *(0.5.2 — FIXED in 0.7.0)*: in
   `uart.sv`, `counter #(.W(3))` and `counter #(.W(4))` both elaborated to a
   single `counter` model with a 4-bit `count` port. 0.7.0 correctly
   produces `counter` and `counter__elab1`.
2. **Process-killing exception on multi-output primitives** *(still in
   0.7.0)*:
   `Instance.is_buf()/is_const()/is_inv()` →
   `NLDB0::getPrimitiveTruthTable` throws an uncaught C++ `NLException` on
   `naja_fa` ("FA has two outputs") which terminates the interpreter
   (`libc++abi: terminating`). Any design containing an adder kills
   `najaeda.stats.compute_instance_stats`. naja-scope ships its own
   truth-table-free stats walker (`api.get_stats`). The exception should be
   translated to a Python exception, and `is_buf/is_const/is_inv` should
   return False for multi-output primitives.
3. **naja-if snapshots of SV-loaded designs do not reload** *(still in
   0.7.0)*: `dump_naja_if` + `reset` + `load_naja_if` fails with
   `cannot deserialize instance 0: model not found (reference dbID ...)` for
   designs lowered from SystemVerilog (works for the trivial counter-only
   design; fails as soon as comparisons/assigns appear, with or without
   `keep_assigns`). 15-line repro: load `bisect1.sv` (a counter plus
   `assign tick = (count == 8'hFF)`), dump, reset, load. Likely instances
   referencing models in the universe DB (NLDB0) that are not serialized.
   Tracked by `tests/test_zz_snapshot.py::test_snapshot_reload_roundtrip`
   (strict xfail).
4. **`Instance.get_design()` raises on top** *(still in 0.7.0)*:
   `IndexError: pop from empty list` when called on the top instance
   (netlist.py:1536) — guard `len(self.pathIDs) == 0`.
5. **Anonymous primitive *model*** *(0.5.2; not reproduced on this design in
   0.7.0)*: one lowered buffer primitive had an empty model name (showed up
   as `(unnamed)` in stats). Lowered primitive models should always be named.
6. **C++ logging goes to stdout** *(still in 0.7.0)*
   (`[naja] [warning] ...`), which corrupts
   stdio JSON-RPC transports. naja-scope reroutes fd 1 to stderr in
   `server.main()`. A way to direct naja logs to stderr (or a Python logging
   bridge) would help every embedder.

## Frontend coverage notes (beta, expected but user-facing)

- Sequential lowering rejects 3+-branch `if/else if` chains in `always_ff`
  and `case` inside `always_ff` ("fallback currently supports only multi-LHS
  reset branches"). Next-state logic must live in `always_comb`. This is
  DESIGN.md risk #1; error messages are good (file:line), naja-scope
  surfaces them verbatim.
- `===` in case statements is lowered as 2-state comparison with a warning.
