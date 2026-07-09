# naja-scope

## Always use the low-level naja Python API, never najaeda's high-level API

When writing code that talks to najaeda — inside `src/naja_scope/` or in
throwaway exploration scripts — always go through `from najaeda import naja`
(the raw `naja.so` binding: `NLUniverse`, `NLDB`, `SNL*` objects) and never
through `najaeda.netlist` (the high-level `load_verilog`/`load_system_verilog`/
`Instance`/`Term` wrapper).

**Why:** `src/naja_scope/loader.py` is deliberately built this way already —
see its module docstring: "driven directly through the raw `naja` DB/universe
API ... rather than the high-level najaeda.netlist loaders. This keeps
naja-scope on the raw layer end to end." The high-level API is a convenience
wrapper that can lag, rename, or diverge from the raw layer (e.g. the
`allow_unknown_designs` -> `blackbox_unknown_modules` rename in najaeda 0.7.11
broke the raw `NLDB.loadVerilog` binding's kwarg, independent of whatever the
`najaeda.netlist` wrapper did to stay compatible). Exploring or prototyping
against the high-level API produces findings that don't reflect what
naja-scope itself does at runtime.

**How to apply:** For any one-off inspection (checking pin roles, instance
types, hierarchy, etc.), use `naja.NLUniverse` / `naja.NLDB` /
`naja.SNL*` objects directly, the same way `loader.py`, `session.py`, and
`api.py` do. Do not import or call `najaeda.netlist.*` even for quick
throwaway scripts.
