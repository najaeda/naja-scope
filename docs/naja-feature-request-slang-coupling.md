# Feature request prompt: keep the slang `Compilation` alive + expose the SNL↔slang link (PyNaja `ast_symbol_of` / `snl_objects_of`)

*The phase-2 "living intent layer" productization (DESIGN.md "Phase 2" option 2/3;
NAJAEDA_NOTES.md "Proposal B — SNL↔slang coupling"). This is the naja-side half;
naja-scope rides on top. Anchors are into the naja3 tree, verified at HEAD on
2026-06-25. The naja-scope-side prototype (route 1, separate pyslang
re-elaboration) is built and **passed its eval gate** on cva6-small — so this is
now justified, not speculative (see naja-scope docs/phase2-plan.md §4 "GATE
RESULT").*

## Problem

During SystemVerilog lowering, `SNLSVConstructor` builds a full
`slang::ast::Compilation` (the elaborated AST: enum/typedef types, symbolic
parameter expressions, process structure, assertions) and then **destroys it** —
`compilation_` is a `std::unique_ptr<slang::ast::Compilation>` member moved in at
build time (`SNLSVConstructor.cpp:1166,1193,1259,2010`; used e.g. at
`:1050 compilation_->getRoot()`) and freed when the constructor goes out of scope.

Everything that distinguishes "the netlist" from "the source intent" dies with it:
enum state-name encodings, the *formula* behind a baked-in width, sync/async reset
structure, SVA. naja-scope can recover some of this by **re-elaborating the same
source in a separate pyslang** and matching by name/source-range — and that is
enough for *named, declaration-level* objects (the gate proved it). But the
reconstructed link is lossy exactly where lowering fans out:

- **uniquification** maps one slang `InstanceBodySymbol` → N SNL designs;
- **bit-blasting** maps one statement → many anonymous FF/gate primitives with
  **no slang name** (naja-scope's prototype must *reject* `#<id>` refs);
- **generate / one-line-to-N** collapses many objects onto one source range.

The exact correspondence only exists **at the moment of lowering**, inside naja's
C++, where the fan-out is in hand. Capturing it there — and keeping the
Compilation that the symbols point into alive — is the only sound way to land on
the exact source intent for *every* object in both directions (DESIGN.md §8: the
moat is "Slang + Naja + bidirectional binding").

## Task

Two tiers (NAJAEDA_NOTES Proposal B), independently shippable:

- **Tier 1 — persistent key (`sv_symbol_path`).** Cheap, snapshot-survivable,
  no live pointers. Filed separately: see
  `docs/naja-feature-request-sv-symbol-path.md`. It is the cold-start fallback
  this FR degrades to when the Compilation is absent.
- **Tier 2 — exact live binding (this FR).** Keep the one `Compilation` alive for
  the session and build a `SNLDesignObject* ↔ const slang::ast::Symbol*` bimap at
  the lowering site, exposed to Python as raw-pointer hops.

This avoids both costs of the route-1 prototype: **double elaboration** (naja
already built this AST) and the **divergence risk** of two independent
elaborations disagreeing (one elaboration is consistent by construction).

## Required Python surface (the consumer contract)

```python
# 1. forward: an elaborated SNL object -> its slang symbol (raw pointer hop)
sym = naja.ast_symbol_of(snl_object)        # None if not source-derived
# 2. inverse: a slang symbol -> the SNL object(s) it lowered to (1 -> N)
objs = naja.snl_objects_of(slang_symbol)    # list; empty if none
# 3. lifetime: the Compilation must outlive the constructor and be reachable
comp = naja.live_compilation()              # the session-owned Compilation, or None
```

`sym` is consumed by **pyslang riding on top** for the actual intent queries
(types, params, processes, assertions) — LLMs already know that API. The win is
that the *link* is an in-engine pointer lookup, not re-elaboration (route-1 cost)
nor a serialized copy. If exposing a raw `slang::ast::Symbol*` across the pybind
boundary is undesirable, the fallback is a **curated** C++ surface over the same
bimap (`get_type`/`get_parameters(symbolic=True)`/`get_process`/`find_assertions`,
DESIGN.md option 2) — same internal link, smaller surface.

## Changes (anchors in the naja3 tree, HEAD 2026-06-25)

**1. Move `Compilation` ownership off the constructor — `SNLSVConstructor.cpp`**
- `compilation_` is moved in at `:1166/:1193/:1259/:2010` and dies with the
  `SNLSVConstructorImpl`. Hand it to a **session-lifetime owner** (a new object
  owning both the SNL DB and the Compilation), so the AST and the bimap pointers
  stay valid for the whole query session. This is a contained ownership refactor,
  not a redesign — `getRoot()` etc. (`:1050`) keep working.

**2. Build the bimap at the uniquification clone site — `SNLSVConstructor.cpp`**
- `cloneRTLInfos` (`:3512`, calling `toInfos->cloneInfos(*fromInfos)` at `:3534`)
  is where one slang body fans out to N SNL designs; the existing
  `annotateSourceInfo(design, getSourceRange(definition))` (`:2755`) is where each
  object is already tied to its source. Stamp `(SNLDesignObject* ↔ Symbol*)` here
  — a path-only map collides exactly at this 1→N point (NAJAEDA_NOTES Proposal B,
  DESIGN.md "the coupling map, not the layers"). Raw pointers are safe: the
  Compilation is alive and immutable in-session.

**3. Bind the accessors — `src/nl/python/naja_wrapping/`**
- New `PyNaja`-level free functions `ast_symbol_of` / `snl_objects_of` /
  `live_compilation`, mirroring the wrapping pattern of the NLID work
  (`docs/naja-feature-request-NLID-python-class.md`). Wrapping a
  `const slang::ast::Symbol*` is the one non-mechanical part — see the ABI note.

## The one real decision: pyslang ABI lockstep

For `ast_symbol_of` to return a symbol that **pyslang** can query, pyslang must be
built from naja's **exact slang fork commit**, or naja.so must expose a thin
slang-symbol accessor compiled in-tree. naja's slang is plain upstream master
(`thirdparty/slang` at `a6285d93`, and the submodule already ships `pyslang/`), so
an exact-commit pyslang build is available — this is the gate between "option 3,
powerful (full pyslang on the shared symbol)" and "option 2, safe (curated C++
API)". Decide deliberately; the curated API is the safe default if the ABI
coupling proves brittle to maintain.

## Tests

- **C++**: for a design with a uniquified module instantiated N times, assert
  `snl_objects_of(body_symbol)` returns the N distinct SNL designs, and
  `ast_symbol_of` round-trips each back to that one symbol.
- **C++**: a bit-blasted register → assert each lowered FF primitive maps to the
  declaring variable/statement symbol (the case name-matching cannot reach).
- **Python**: `ast_symbol_of(reg)` then pyslang reads `.type` → enum members;
  `ast_symbol_of(param)` → `.syntax` initializer text == the source formula.

## Acceptance criteria

1. The `Compilation` survives `SNLSVConstructor` teardown and is reachable for the
   session lifetime.
2. `ast_symbol_of` / `snl_objects_of` round-trip exactly across uniquification
   (1→N) and bit-blasting (anonymous primitives), where source-range/name
   matching is known to collide.
3. No measurable change to lowering output; the bimap is additive.
4. Cold start (snapshot SNL, no Compilation) degrades cleanly to the tier-1
   `sv_symbol_path` rebind, never a crash.

## Consuming side (what naja-scope does once this lands)

- naja-scope's `IntentProvider` (`src/naja_scope/intent.py`) switches its
  name-keyed hierarchy descent for the exact `ast_symbol_of` link — and `get_intent`
  starts answering for **anonymous lowered primitives** (`#<id>`), which the
  route-1 prototype must refuse today.
- Drops the separate pyslang re-elaboration (no double elaboration, no divergence
  risk), keeping pyslang purely as the query engine on the shared symbol.
- Cold start uses tier-1 `sv_symbol_path` to re-bind on warm-up; until then
  `get_intent` returns "intent layer not loaded" (already implemented).
