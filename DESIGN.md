# naja-scope — design notes

*Architecture analysis for naja-scope, an agent-facing query layer over najaeda (working title was "naja-graphify"). Drafted 2026-06-12 with Claude Code.*

## Naming candidates

- **najascope** (chosen, as naja-scope) — "scope" reads as oscilloscope probing, variable scope, and design scope; pip-friendly; clearly in the naja family.
- **naja-atlas** — a pre-built map you consult instead of re-surveying the territory; good metaphor for the token-efficiency pitch.
- **netlens** — works standalone, away from the naja brand.
- Playful: **charmer** (agents "charming the snake"); memorable but hard to take seriously in EDA.

## Verdict

The idea is sound, but the framing contains a trap: **do not build a graph — the graph already exists.** Naja's SNL is already an in-memory graph database of the design with typed objects, fast traversal, and equipotentials. Exporting it into a second store (Neo4j, GraphML, triples) creates sync, staleness, and ops problems in exchange for a query language LLMs use worse than function calls. Graphify needs Neo4j because source code isn't a graph until you make it one; here the situation is inverted.

The product is **~12 MCP tools plus a discipline about response sizes**, not a graph platform. The differentiated asset is the bidirectional source↔netlist binding.

## Facts verified in the naja repo (updated 2026-06-15)

1. **The netlist→source back-link is now exposed through Python — at both API levels (naja #389 "rework RTL source infos" + #390 "wrap source access in Python", landed 2026-06-15).** This was previously flagged as the single highest-leverage piece of engineering; it is done. Details:
   - Storage reworked: source location is now a *typed* `SNLSourceLoc` slot on `SNLRTLInfos` (`file, line, endLine, column, endColumn`), not the old free-form `sv_src_*` string key/value pairs. Rare key/values still live in an optional map; the Verilog dumper gets them via `getDumpAttributes()`.
   - **Native low-level API** (`naja` module / PySNL): `SNLDesign` and `SNLDesignObject` now expose `hasSourceLoc()` and `getSourceLoc()`. `getSourceLoc()` returns a tuple `(file, line, column, end_line, end_column)` (or `None`). This is the first-level access naja-scope should build on.
   - **High-level najaeda API**: a frozen `SourceRange` dataclass (`file, line, end_line, column, end_column`) plus `get_source_range()` on `Instance`, `Term`, and `Net`, each returning `Optional[SourceRange]`.
   - Footgun to note: the native tuple order is `(file, line, column, end_line, end_column)` but the `SourceRange` dataclass field order is `(file, line, end_line, column, end_column)`. The najaeda wrapper remaps correctly; code using the native API directly must respect the tuple order.
2. **This API is now on PyPI as najaeda 0.7.2** (published 2026-06-16; verified to ship both the native `getSourceLoc()`/`hasSourceLoc()` and the high-level `SourceRange` + `get_source_range()`). The earlier gap (0.5.2 predated #389/#390) is closed. **The pin floor is `najaeda>=0.7.6`**: 0.7.4 fixes the naja-if snapshot reload for SystemVerilog-loaded designs (the "model not found" deserialize bug present 0.5.2–0.7.3), the only re-entrant RTLInfos persistence path (see §5 and NAJAEDA_NOTES.md bug §3); 0.7.5 adds `naja.SNLLogicalCone` (the C++ cone backend — DESIGN.md §6 `trace_cone`); 0.7.6 adds combinatorial modeling on the lowered logic gates so the cone crosses them and reaches the cross-hierarchy flop frontier. `cone.py` is now built entirely on `SNLLogicalCone` (the hand-rolled equipotential BFS is gone). 0.7.6 is **on PyPI**, so the canonical dev path is the 3.11 `.venv` (PyPI najaeda, `--system-site-packages`); the local naja build (`/Users/xtof/WORK/naja3`, Python 3.14, via the `.venv314` dev venv) is kept only for running against naja HEAD ahead of a release — see NAJAEDA_NOTES.md §4. naja-if serialization is unchanged across 0.7.4–0.7.6, so existing snapshots stay valid.
3. `load_system_verilog` can emit the Slang elaborated AST as JSON with source info (`SystemVerilogConfig.elaborated_ast_json_path`, `include_source_info_in_elaborated_ast_json`). A source-intent layer exists as a byproduct.
4. A prototype najaeda MCP server already exists (load_verilog, load_liberty, load_primitives, top_summary, list_child_instances, instance_stats, dump_naja_if, load_naja_if, reset_universe). The MVP is an extension of it.
5. naja-if (Cap'n Proto) snapshots give fast session reload, avoiding re-elaboration.
6. Recent work lowers always_ff/latches to FF/latch primitives, so "which always_ff updates this register" is answerable structurally.

### Two access levels (use the right one)

naja-scope sits on najaeda, but najaeda is itself a *simplification layer* over the native `naja` bindings (PySNL). Both are importable from Python:

- **najaeda high-level API** (`Instance`/`Term`/`Net`, `get_source_range()`, path-string navigation) — the default surface for the fixed MCP tools. Stable, ergonomic, what most tool handlers should call.
- **native low-level API** (`from najaeda import naja`; `SNLDesign`/`SNLDesignObject`, `getSourceLoc()`, occurrences/paths) — more powerful and lower-overhead. **naja-scope is built entirely on this layer** (`snl.py` + `loader.py`); the high-level `najaeda.netlist` wrappers are not used. It is also exposed (read-only) through `query_python` as the agent's power escape hatch. What agents repeatedly reach for here is the roadmap for what the raw helper layer should absorb.

## 1. Conceptual architecture

Four components:

- **Indexing phase** — run Slang→Naja elaboration once per design revision. Persist: (a) a naja-if snapshot (elaboration cache; load in seconds vs minutes), (b) a small SQLite sidecar for what the in-memory netlist can't answer cheaply: FTS name index for fuzzy `find()`, deterministic per-module "cards", and a content-hash-keyed cache for any future LLM summaries. The elaborated AST JSON is an optional third artifact — keep on disk, never load wholesale (it can exceed source size).
- **Query engine** — the live najaeda session inside the MCP server process. No separate engine: `get_equipotential`, `get_leaf_drivers`, `get_flat_fanout` already are the engine.
- **Agent interface** — a stateful MCP server (one design per process for v1). Statefulness amortizes the expensive thing: the loaded design.
- **Caching** — snapshot (elaboration), SQLite (index), nothing per-query (cheap against a loaded netlist).

Cut from the original component list: a distinct "graph construction" phase and a "graph storage" layer. Both are the netlist.

## 2. Graph design — two layers, one identity scheme

**Naja layer (the spine — "what is connected to what"):**
- Nodes: design (post-uniquification module), instance, term/pin bit, net bit, equipotential, primitive (FF/latch/gate).
- Edges: instance-of, child-of, connects (term↔net), drives/loads, equipotential membership (the cross-hierarchy electrical edge no source-level tool has).
- Properties: direction, width, msb/lsb, truth tables, sequential/clock-related classification, and source ranges (`SourceRange` / `getSourceLoc()` — now exposed at both API levels).

**Slang layer (annotations — "what the designer meant"):** not a graph in v1. Two mechanisms: (a) source ranges attached to netlist objects; (b) lazily extracted facts from the AST JSON: parameter values per elaborated instance, type names before bit-blasting, package origins, generate provenance, process kinds.

**Lost going Slang→Naja** (hence annotation-layer-only): comments and macros; symbolic parameter expressions (value kept, formula lost); struct/enum/interface types (enum state names are a real loss for FSM questions); procedural control structure (if/case → mux trees); functions/tasks as abstractions; assertions/SVA; everything non-synthesizable.

**Strategic scope decision:** a naja-spined system cannot answer questions about UVM testbenches. v1 targets design/RTL questions, not DV — document this explicitly or DV users will hit the wall and blame the tool.

**Combined graph?** No. The join key is the netlist object; the Slang layer is reached through it via source ranges. A merged property graph forces ontology questions no agent query needs.

## 3. Agent workflow: "What drives top.u_uart.tx_o?"

```
1. resolve("top.u_uart.tx_o")
   → { kind:"term", id:"u_uart.tx_o", dir:"output", width:1 }        (~80 tokens)
2. get_drivers({ term:"u_uart.tx_o" })
   → { equipotential:…, leaf_drivers:[{ inst:"u_uart.u_tx.tx_q_reg",
       model:"NAJA_DFF", pin:"Q", src:"rtl/uart_tx.sv:142-149" }] }  (~150 tokens)
3. get_source({ object:"u_uart.u_tx.tx_q_reg", context:4 })
   → 12 lines of the always_ff block                                  (~200 tokens)
```

Three calls, <600 tokens, answer plus quotable source. Same skeleton answers "which always_ff updates register X" and "what cone feeds output Y" (trace_cone with stop-at-flops, frontier summary).

**Key failure mode:** name resolution. User-typed paths must survive bit-blasting, generate suffixes, uniquification, escaped names. If `resolve()` is brittle, agents fall back to grep and the value proposition dies. Build fuzzy matching and "did you mean" first.

## 4. Token efficiency — honest accounting

- **Direct source retrieval:** 3–6 file reads, 15k–80k tokens, several turns; fails outright when connectivity isn't textual (generate loops, interfaces, parameter-dependent wiring). On MegaBoom-class designs grep isn't slow, it's wrong.
- **Graph retrieval:** 0.5–1k tokens for navigation questions → 20–100× reduction on that class.
- **Graph + summaries:** ~200-token module cards replace 5–50k-token module reads for orientation; marginal win over graph-only is modest because deterministic cards cover most orientation needs.

Limitations: behavioral questions still end in reading source (the graph routes to the right 50 lines instead of the right 5 files → 2–5× on mixed sessions, not 50×); cone queries can be token-explosive — structural compression (counts, frontiers, stop-at-flops, max_nodes) is a correctness requirement, not polish; tool schemas cost ~1–2k tokens/session (net-negative on toy designs).

Under-claimed benefit: **confidentiality** — graph queries leak far less proprietary RTL to cloud models than source retrieval. May matter more than tokens to semiconductor customers.

## 5. Storage

- **Live SNL in memory** — primary store.
- **naja-if snapshot** — persistence; already implemented.
- **SQLite** — sidecar only (FTS name search, module cards, summary cache). Not the graph store.
- **JSONL** — export format at most. **GraphML** — visualization export if asked; never a store. **Parquet** — only for bulk analytics (pandas_stats direction).
- **Neo4j / graph DBs** — avoid. Ops + sync burden; Cypher-writing agents hallucinate schemas. The main thing *not* to copy from Graphify.

All derived artifacts keyed by a content hash of the input file list so staleness is detectable.

## 6. MCP tool API

Conventions (matter more than the tool list): object references are hierarchical path strings; all lists paginated (limit ~50, cursor, total); responses include `src` ranges where known; errors return structured suggestions.

| Tool | Request (essentials) | Response (essentials) |
|---|---|---|
| `resolve` | `{path_or_pattern, kind?}` | `[{kind, path, dir?, width?, model?}]` |
| `get_hierarchy` | `{instance, depth=1, limit?, cursor?}` | tree of NON-ASSIGN children only (submodules + leaf primitives); per-node `children_total`, `assign_count`, `non_assign_total`, per-child `leaf` flag; root paginated via `next_cursor`/`has_more`, deeper levels via `children_truncated` |
| `get_drivers` / `get_loads` | `{term_or_net}` | `{equipotential_size, leaf:[{inst,model,pin,src}], top:[…]}` |
| `trace_cone` | `{term, dir:fanin\|fanout, max_frontier}` | `{node_count, counts_by_kind, frontier:{flops,ports,blackboxes}+counts, cross_hierarchy, counts_by_model, truncated}` (naja `SNLLogicalCone`) |
| `get_source` | `{object, context_lines=3}` | `{file, start, end, text}` |
| `get_module_card` | `{module}` | ports, params, counts, clocks/resets, protocol guess |
| `find` | `{glob_or_regex, kind, limit}` | paginated matches |
| `get_stats` | `{instance}` | exists today (instance_stats) |
| `query_python` | `{code, timeout}` | stdout/repr, sandboxed |

`query_python` is the cheapest experiment: najaeda itself is the query language; LLMs know Python, not a future Cypher dialect. Watch what agents write there and promote recurring patterns into first-class tools.

## 7. LLM usage

**No LLM at indexing time for v1.** Cost scales with design size; summaries go stale on every edit; hallucinated summaries silently poison agent reasoning; the querying agent is already a frontier model.

- Always deterministic: connectivity, hierarchy, names, source ranges, counts, port lists, parameter values, truth tables.
- Name-based guesses (label them as such — never deterministic): clock/reset identification and reset polarity, and protocol detection by port-name/direction patterns (~80–90% at zero tokens). **Clock/reset detection by name is a workaround.** Names are conventions, not semantics; the sound source is SDC (`create_clock` …) constraints plus back-propagation from the clock/reset pins of sequential cells, never the signal name. The `get_module_card` clock/reset fields are flagged `name_based_workaround` until structural detection lands (needs naja to expose FF clock/reset pin roles + SDC ingest).
- Defensible LLM uses (lazy, cached by content hash): module purpose summaries on first get_module_card, cone explanations on demand, protocol fallback for nonstandard naming.
- Local LLM: only interesting for the confidentiality story; build when a customer asks.

## 8. Competitive position

- **Graphify:** AST-level, lexical, no elaboration — cannot know post-elaboration connectivity. The moat is exactly what it can't reach.
- **Sourcegraph / LSP (verible-ls, slang LSP):** go-to-definition at source level; stops at instantiation boundaries. Complementary, not competitive.
- **Pure Slang tooling:** intent without flattened connectivity; "Slang + MCP" is a weekend project and will be commoditized. Slang + Naja + bidirectional binding is not.
- **Direct netlist DB (Yosys/odb MCP experiments, commercial agents):** closest competition. Differentiators: pip-installable, no synthesis step, hierarchical netlist, robust source back-links (Yosys `src` attrs exist but names get mangled), snapshots for instant session start.

One sentence: *the only open, pip-installable system where an agent can traverse elaborated connectivity and land on the exact source lines that produced it, in both directions.*

## 9. MVP (2–4 weeks)

**Week 0 — done:** the source-access API shipped in najaeda 0.7.2 on PyPI (see fact 2). Pin `najaeda>=0.7.6` in `pyproject.toml` (0.7.4 fixes the snapshot-reload bug; 0.7.5 adds SNLLogicalCone; 0.7.6 adds gate modeling for the cone — fact 2). 0.7.6 is on PyPI, so the canonical dev path is the 3.11 `.venv` (PyPI najaeda); the local naja3 build (`.venv314`, Python 3.14) is kept only for naja HEAD ahead of a release. The MVP is unblocked.

- **Week 1:** ~~expose source info through Python~~ — **done in naja (#389/#390), shipped in najaeda 0.7.2**. Build the source-access into the tools directly: `get_source` now reads `Instance/Term/Net.get_source_range()` (high-level) or `getSourceLoc()` (native). Add `resolve`, `get_drivers`, `get_loads`, `get_source`, `find` to the existing MCP server.
- **Week 2:** `trace_cone` (stop-at-flops, hard max_nodes), deterministic `get_module_card`, pagination everywhere.
- **Week 3 (the real deliverable):** the eval — 25–30 questions with golden answers across two regress designs (UART-class small + cva6/MegaBoom-class large). Claude Code with the MCP server vs plain Claude Code with grep; measure correctness, tokens, turns. Include a handful of intent-class questions (FSM state names, reset polarity, symbolic parameter meaning) answered the phase-1 way (source-range + read) to baseline what the phase-2 living AST would improve. If the win isn't decisive on the large design, months are saved.
- **Week 4:** `query_python` sandbox, docs, publish.

Deferred: Slang-side graph store, all LLM enrichment, protocol inference beyond heuristics, multi-design servers, every graph database, GraphML.

### Phase-1 prep hooks for phase 2 (cheap, do now)

1. Record `sv_symbol_path` (slang hierarchical path string) as an RTL info at lowering time, alongside the typed `SNLSourceLoc` — a persistent join key that lets a future live AST re-bind to a snapshot-loaded SNL. (This is a naja-side frontend change, request it of najaeda; could ride on the same `SNLRTLInfos` rework that #389 introduced.)
2. Split tool handlers behind a provider interface: `StructuralProvider` (SNL, always present) and `IntentProvider` (optional, absent in MVP), so phase 2 plugs in rather than rewrites.
3. `query_python` exposes the raw layer only — `naja` (PySNL), `snl` (naja-scope's raw helpers: InstNode, top_node, iter_designs, equipotentials), `session`, and `top`. Read-only by convention/gating in v1. (Earlier drafts exposed high-level `najaeda.netlist` too; the implementation standardised on raw SNL end to end, so the escape hatch follows suit.) What agents repeatedly reach for here is the roadmap for what the raw helpers should absorb — the sandbox doubles as telemetry.

## Phase 2: living intent layer (slang AST + SNL coupled in memory)

Direction chosen 2026-06: rather than the static AST-JSON sidecar, keep the `slang::ast::Compilation` alive after lowering, coupled with the C++ SNL, both agent-accessible. Today the compilation dies with `SNLSVConstructor` (which owns it as a `unique_ptr` member, see `compilation_` in SNLSVConstructor.cpp ~2333) — keeping it alive is a contained ownership refactor (move to a session-lifetime object), not a redesign.

**What it buys over the JSON dump** (a corpse you can search but not interrogate): on-demand queries for enum/struct/interface types before bit-blasting (FSM state names), symbolic parameter expressions, process structure (which always_ff, sensitivity, sync/async reset), assertions/SVA, packages/imports, generate provenance — and slang's analysis layer can answer "what drives X" at the procedural/word level, the intent-side complement to SNL's structural answer. A live compilation can also contain non-synthesizable code, softening the RTL-only scope caveat (SNL still won't represent testbenches, but scope/definition/assertion questions become answerable).

**Snapshot asymmetry (shapes everything):** SNL reloads from naja-if in seconds; a Compilation is bump-allocated and pointer-rich — never serializable, only obtainable by re-elaboration (minutes at scale). Two tiers are therefore inherent:
- Cold start: SNL from snapshot + persisted ranges; intent tools degrade gracefully ("source range provided, intent layer not loaded").
- Warm session: SNL + living AST, full capability. `load(intent=true/false)` knob; memory budget roughly doubles (each layer is GB-class on large designs).

**The real engineering — the coupling map, not the layers:** build a direct `SNLDesignObject* ↔ const slang::ast::Symbol*` map during lowering (raw pointers safe in-session; compilation is alive and immutable). Source-range joins are lossy keys: generate loops map one line to N instances; uniquification maps one slang InstanceBodySymbol to several SNL designs; one statement lowers to many primitives. The map must be maintained exactly where `cloneRTLInfos` already runs — uniquification is where naive maps break. The persisted counterpart is `sv_symbol_path` (prep hook 1).

**Exposure options, in increasing ambition:**
1. Separate pyslang re-elaboration in the same server process — zero naja C++ work; double elaboration/memory; divergence risk (different slang version/flags → mismatched hierarchies). Right for prototyping which intent queries matter; wrong as product.
2. Compilation kept inside naja.so, minimal curated query API in the bindings — `get_type(ref)`, `get_parameters(ref, symbolic=True)`, `get_process(reg_ref)`, `find_assertions(scope)`. One elaboration, exact coupling, controlled surface. **The productizable path.**
3. Full pyslang interop on the shared live compilation across pybind module boundaries — agents get the whole pyslang API in `query_python` (LLMs already know pyslang), at the cost of ABI/version lockstep between naja.so and a pyslang built from the exact slang fork commit. Fragile; only if option-2 usage proves the long tail is needed.

Sequence: prototype with 1, productize with 2, hold 3 in reserve. Phase 2 stays strictly out of the MVP gate — it is the kind of problem that eats schedules, and the week-3 eval's intent-question baseline is what justifies (or kills) it with data.

## Risks, ranked

1. **Frontend coverage is the product risk.** The layer inherits every gap in SV lowering; "construct not supported" on a user's real design kills trust, and the user blames the agent layer. Eval designs must be fully digested; errors must degrade informatively.
2. **Name fidelity** through bit-blasting/generates/uniquification — test round-tripping before features.
3. **Scope honesty:** RTL-design tool, not DV. Non-synthesizable SV is invisible to the spine.
4. **Output explosion:** token-bounded responses are a correctness requirement.
5. **Premature platform-building:** everything in the graph-store/ontology/enrichment direction is deferrable; none of it is needed to win the week-3 eval.

Bottom line: the distance between what exists (SNL, RTL infos, snapshots, prototype MCP server) and a defensible MVP is mostly one Python binding and eight tool handlers.
