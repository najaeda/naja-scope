# Feature request prompt: persist the relink key (slang hierarchical path → intrinsic key) as a typed RTL info

*DESIGN.md phase-1 prep hook 1; NAJAEDA_NOTES.md Proposal A (typed slot) + Proposal
B tier 1 (persistent key). The snapshot-survivable join key behind the **cold
relink** specified in `docs/naja-feature-request-slang-coupling.md` ("Cold tier —
exact relink"). Anchors into the naja3 tree, verified at HEAD 2026-06-25.*

> **Status (2026-06-26): DEFERRED with its cold tier.** This key exists only to
> serve the cold relink in the coupling FR — which is deferred, because cold
> elaboration on najaeda 0.7.8 is cheap (~12s cva6-small / ~29s cva6-full; the old
> ~68 min was a since-removed Python pass). Don't build this until the cold-tier
> gate (snapshot-reload-vs-re-elaborate measurement) is met. Spec retained as
> design of record.
>
> **Design update (2026-06-26):** a bare hierarchical path is **not** sufficient —
> it collides at uniquification (one path → N parameterized bodies) and needs
> bit/element disambiguation. The persisted key is the **intrinsic key** from the
> coupling FR: `hierarchical path + parameter-set signature + bit/array-element
> index`. The serialization mechanism below (typed slot, intern the id, egress
> through naja-if) is unchanged; only the key's *contents* widen. The cold tier
> uses it to relink a fresh re-elaboration, **fail-closed** on a stored
> slang-version + source fingerprint mismatch. Read the coupling FR first; this
> doc covers the persistence plumbing.

## Problem

A `slang::ast::Compilation` is bump-allocated and pointer-rich — **never
serializable**; it only exists by re-elaboration. So the live SNL↔slang bimap
(tier 2) cannot survive a naja-if snapshot. After a cold snapshot load (SNL in
seconds, no Compilation), the intent layer has no way to re-bind a freshly
re-elaborated AST to the snapshot-loaded SNL objects: source ranges alone are
lossy (one line → N instances), and lowered names are not relied upon.

What *is* stable and regenerable is the **slang hierarchical path** of each object.
slang already computes it during lowering — `symbol.getHierarchicalPath()` at
`SNLSVConstructor.cpp:16313`. If interned and persisted per object, a cold
re-elaboration can re-bind by walking slang symbols and matching paths — no live
pointers, no serialized AST.

## Task

Stamp each annotated `SNLDesignObject` with a persistent `sv_symbol_path` join key
at lowering, alongside the existing `sv_src_*` source range, and **serialize it
through naja-if** (the only re-entrant persistence path — NAJAEDA_NOTES "Scope
decision"). Egress to Python so a consumer can read it.

Best done as part of **Proposal A Level-1** (the typed source-loc struct), which
already reserves the slot:

```cpp
struct SNLSourceLoc {            // 16-byte POD, replaces 5 string-map entries
  uint32_t fileId; uint32_t line, endLine; uint16_t column, endColumn;
};
class SNLRTLInfos {
  std::optional<SNLSourceLoc> sourceLoc_;
  uint32_t symbolPathId_ {kInvalid};   // <-- this FR: interned sv_symbol_path
  std::unique_ptr<Infos> extra_;       // nullptr unless rare k/v used
};
```

`symbolPathId_` indexes a per-DB string table of hierarchical paths (slang can
regenerate the string, so only the id need persist).

## Changes (anchors in the naja3 tree, HEAD 2026-06-25)

1. **Capture** — at the per-object annotation site `annotateSourceInfo(design,
   getSourceRange(definition))` (`SNLSVConstructor.cpp:2755`), also intern
   `symbol.getHierarchicalPath()` (`:16313`) into `symbolPathId_`.
2. **Clone** — `cloneRTLInfos`/`cloneInfos` (`:3512`/`:3534`) copies the id like
   any other field (a `uint32_t`, vs today's 5 string allocations per clone).
3. **Serialize** — emit `symbolPathId_` (and the path string table) through
   naja-if capnp. RTL infos are **not** serialized today
   (`getDumpableProperties()` only dumps `NajaDumpableProperty*`); this FR puts
   that egress on the critical path (NAJAEDA_NOTES Proposal A Level 0).
4. **Egress** — bind `SNLDesignObject.getSymbolPath()` (resolve id → string) to
   PyNaja.

## Tests

- Round-trip: dump a snapshot, reload, assert `getSymbolPath()` returns the same
  hierarchical path string for a known register (it must survive naja-if, like
  `getSourceLoc()` does since 0.7.4).
- A cold re-elaboration walks slang symbols and re-binds: for the privilege
  register, `symbol.getHierarchicalPath()` of the freshly elaborated AST ==
  the snapshot-loaded SNL object's `getSymbolPath()`.

## Acceptance criteria

1. Every source-annotated object carries an intrinsic relink key (path +
   parameter-set signature + bit/element index), unique per linked symbol (or a
   clear, stable absence for objects with no single source symbol — see the
   coupling FR's residual cases).
2. It survives a naja-if dump→reload unchanged, alongside the slang-version pin
   and source fingerprint the relink guard checks.
3. The clone cost is an int copy, not string allocation (Proposal A Level-1).

## Consuming side (naja-scope)

The cold relink is a **naja core** operation (`naja.relink_intent()` /
`SNLSVIntent::relink()`, coupling FR), symmetric for C++ binaries and Python: it
re-elaborates slang and rebuilds the bimap by joining each object's stored
intrinsic key to the recomputed key of the fresh AST, **fail-closed** on a
slang-version or source-fingerprint mismatch. `Session.load_intent` after a cold
snapshot load just calls it. Until this lands, cold-start `get_intent` returns
"intent layer not loaded" (implemented).
