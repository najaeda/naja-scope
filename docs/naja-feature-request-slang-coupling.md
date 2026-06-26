# Feature request: SNL↔slang coupling — a C++-core bimap + curated intent API, warm and cold

*The phase-2 "living intent layer", productized. Supersedes the route-1 prototype
(separate pyslang re-elaboration, DESIGN.md "Exposure options" option 1) and the
in-tree-pyslang idea (option 3) — both rejected below. This is the naja-side work;
naja-scope rides on top as a thin, pyslang-free client. The route-1 prototype
(`src/naja_scope/intent.py`) passed its eval gate on cva6-small
(docs/phase2-plan.md §4) and now serves as the **behavioral reference spec** for
the C++ port. Design locked 2026-06-26 with the naja author.*

## Status — what already landed (najaeda 0.7.8 preview)

The warm bimap substrate exists in the local naja build
(`/Users/xtof/WORK/naja3`, `PYTHONPATH=.../naja3/build/test/najaeda`):

- `NLDB.loadSystemVerilog(..., keep_ast_link=True)` retains the live
  `slang::ast::Compilation` past `SNLSVConstructor` teardown
  (`PyNLDB.cpp:295` → `options.keepASTLink`).
- `naja.live_compilation()`, `naja.ast_symbol_of(obj)`, `naja.snl_objects_of(sym)`
  (`PyNaja.cpp:194/205/229`), backed by `SNLSVLiveASTLinkRegistry`
  (`findForObject` / `findForSymbol` / `getObjects`).
- Verified: the anonymous bit-blasted FF `#2` (`naja_dffrn__w2`) resolves through
  `ast_symbol_of` to its declaring variable symbol — the `#<id>` case the route-1
  prototype must refuse. Assign glue (`#0`,`#1`) correctly returns `None`.

What it returns to Python today is a **raw `PyCapsule`** (`naja.slang.Symbol` /
`naja.slang.Compilation`) wrapping a bare `slang::ast::Symbol*` / `Compilation*`.
That half-step is the subject of the decisions below: a raw pointer is unusable
from Python without a slang binding, and we are **not** adding one.

## Two locked constraints (these drive everything)

1. **No pyslang inside naja.** Compiling the slang submodule's pybind bindings
   into the najaeda wheel is a no-go (build/CI/binary-size cost; pybind+ABI
   surface). So Python can never hold a queryable slang object. **Corollary: all
   slang-AST walking happens in C++; consumers receive plain data.**
2. **The bimap must serve pure C++ binaries with no agent in the loop**, behaving
   *exactly* like the Python-wrapped path. So the bimap and the queries built on
   it are a **C++ core capability**, with the Python surface a thin marshaling
   layer over the same C++ — not a parallel implementation.

## Rejected alternatives (why)

- **Option 1 — separate pyslang re-elaboration** (the route-1 prototype): double
  elaboration + divergence risk between two independently elaborated ASTs. Killed.
- **Option 3 — in-tree pyslang on the shared symbol**: would solve the ABI
  problem, but violates constraint 1 (ships a slang binding module). Killed.
- **External PyPI pyslang on the raw capsule**: feeds naja's `Symbol*`
  (slang `v10.0-403-ga6285d931`) to a differently-compiled binding — UB across
  ABI. Killed.
- **Persist the facts only** (cold tier "flavor B": stamp enum members / type
  names / param text as attributes, no relink): cheaper cold path, but cold then
  becomes a frozen subset — the raw bimap and any future question are unavailable
  off a snapshot. Dropped in favor of the exact relink (cold tier below), which
  gives full warm/cold parity.

## Architecture (the locked shape)

```
Layer 0  bimap + live Compilation            [LANDED]
         C++:  ast_symbol_of(obj) -> const Symbol* ;  snl_objects_of(sym) ;
               live_compilation() -> Compilation*

Layer 1  SNLSVIntent — curated C++ query helpers   [NEW: the ported prototype]
         walk slang ONCE in C++, return slang-free POD structs

Layer 2a pure C++ binaries  — call Layer 0 (raw, full slang power) or Layer 1
Layer 2b naja Python C-API  — hand-rolled (no pybind/pyslang): marshal Layer-1
         structs -> plain dicts:  naja.intent_type_of(obj) -> dict, etc.

Layer 3  naja-scope intent.py — thin client over naja.intent_* ; drops pyslang
```

The slang-walking logic lives **once**, in Layer 1, serving the C++ binaries
(constraint 2) and naja-scope (constraint 1) identically.

## Layer 1 — the curated C++ surface (`SNLSVIntent`)

Lives in the SV frontend module next to `SNLSVLiveASTLinkRegistry`. Returns POD
structs with **no slang types in the signature** (so they marshal to Python via
the plain C-API). `valid=false` / empty when there is no live link (cold without a
relink, or a non-source-derived object like assign glue) — never throw.

```cpp
struct EnumMember   { std::string name;   std::string encoding; };   // "2'b11"
struct IntentType {
  bool valid = false;
  std::string typeName;          // declared/alias name  — Type::toString()
  std::string canonicalKind;     // "EnumType","PackedArrayType",…  — getCanonicalType()
  SNLSourceLoc declLoc;          // symbol declaration
  bool isEnum = false;
  unsigned enumWidth = 0;        // baseType.getBitWidth()
  SNLSourceLoc enumDeclLoc;      // where the enum type is declared
  std::vector<EnumMember> members;
};
struct IntentParam  {
  std::string name, value, expr; // value = ConstantValue::toString(); expr = decl RHS
  bool localParam = false;
  SNLSourceLoc loc;
};
struct IntentParams { bool valid = false; std::string module; std::vector<IntentParam> params; };

class SNLSVIntent {
 public:
  static bool          available();                       // live_compilation() != null
  // link-anchored — cover the elaborated hierarchy (registers, ports, instances)
  static IntentType    typeOf(const SNLDesignObject*);    // bimap -> symbol -> walk type
  static IntentParams  parametersOf(const SNLDesignObject*);  // instance/design InstanceBody
  // name-anchored over live_compilation() — packages have no SNL object
  static IntentType    packageMemberType(const std::string& pkg, const std::string& member);
  static IntentParam   packageMember   (const std::string& pkg, const std::string& member);
};
```

slang API hints (the route-1 `intent.py` is the behavioral spec — match its
outputs):
- type: `ValueSymbol::getType()` → `Type::getCanonicalType()`; `Type::toString()`
  for the alias name; `isEnum()`; cast to `EnumType`, `baseType.getBitWidth()`,
  iterate `values()` → `EnumValueSymbol::getValue()` (a `ConstantValue`) + `.name`;
  encodings zero-padded to width (see `_enum_members`).
- params: `ParameterSymbol::getValue()`/`isLocalParam()`; initializer text from the
  declarator `getSyntax()->toString()`, stripped to the RHS (see `_param_expr_text`
  / `_strip_to_rhs`).
- packages: `Compilation::getPackage(name)` → `Scope::find(member)`.

### Addressing carve-out (unavoidable)

The bimap only reaches objects that survived lowering as SNL objects. Registers,
ports, instances → link (and `#<id>` for anonymous primitives, for free). Module
localparams → via the instance's `InstanceBody` (`parametersOf`). **Packages are
never instantiated** → `pkg::NAME` and package typedefs have no SNL object and
must go through `packageMember*` (name-keyed over `live_compilation()`). That one
name-keyed residual cannot be eliminated.

## Layer 2b — the Python C-API surface (no pybind, no pyslang)

Hand-rolled in `PyNaja.cpp`, marshaling Layer-1 POD → plain Python containers:

```python
naja.intent_available() -> bool
naja.intent_type_of(obj) -> dict | None          # IntentType
naja.intent_parameters_of(obj) -> dict | None     # IntentParams
naja.intent_package_member(pkg, name) -> dict | None
```

`obj` is a `SNLDesign` / `SNLDesignObject` (what naja-scope already resolves a ref
to). Python never sees a capsule.

**Deprecate the Python symbol capsule.** `naja.ast_symbol_of` returning a
`naja.slang.Symbol` capsule has no safe Python consumer (constraint 1) — replace
its Python role with the curated `intent_*` calls. Keep the **C++** `ast_symbol_of`
(raw `Symbol*`) as the full-power entry point for binaries. `snl_objects_of` stays
useful in C++ (reverse hop); it needs no Python form for naja-scope's structural→
intent direction.

## Cold tier — exact relink (tier-1, made exact) — **DEFERRED**

> **Status (2026-06-26): deferred, do not build yet.** This tier was justified by
> "cold elaboration is expensive (~68 min CVA6)." That figure was **stale** — it
> was wall-clock dominated by naja-scope's since-removed `ensure_names` O(netlist)
> Python pass. Remeasured on najaeda 0.7.8, cold elaboration is **~12s cva6-small
> / ~29s cva6-full**. At ~30s, re-elaborating warm from scratch is competitive
> with a snapshot reload, so the snapshot cache itself is now a minor convenience
> and the intrinsic-key relink machinery is hard to justify. **Gate before
> building:** measure snapshot reload vs full re-elaboration on the 0.7.8 build;
> build this only if a real, repeated startup cost warrants it. The spec below is
> retained as the design of record for if/when that gate is met. The warm
> `SNLSVIntent` layer above is unaffected and remains committed scope.

A `Compilation` never serializes, so after a cold naja-if load there is no bimap.
The cold tier **re-elaborates the SV once and relinks** the snapshot-loaded SNL
objects to the fresh AST — restoring the *real* bimap, so Layer 0/1/2 behave
identically warm or cold (full parity; this is why "persist facts" was dropped).
Re-elaborating once on a cold load is *not* the rejected double elaboration: naja
did zero elaboration on a snapshot load (it deserialized).

### Relink by intrinsic key — not by traversal order

slang elaborates **multithreaded**, so a positional/DFS-index scheme is a
determinism hazard (one reordering → silent mis-binding). Use an **order-independent
intrinsic key** derived from the symbol's own identity, so the only assumption is
"same source + same slang version → same set of symbols with the same identities"
(not "same order"):

```
intrinsic key = hierarchical path
              + parameter-set signature      (disambiguates uniquified bodies)
              + bit / array-element index     (where slang assigns one)
```

This resolves exactly the fan-out points the old path-only key (`sv_symbol_path`)
could not:
- **generate loops** — slang indexes block-array members (`genblk[3].state_q`):
  the path is already unique.
- **bit-blasting** — one variable symbol → N FF primitives; key = the variable's
  path; each FF (stable SNL `getID`) stores it; `snl_objects_of(var)` rebuilds N.
- **uniquification** — distinct parameterizations are distinct `InstanceBodySymbol`s;
  the **parameter-set signature** in the key prevents two bodies colliding on path.

naja holds the symbol at dump time, so it computes whatever disambiguator a given
symbol needs. Relink recomputes the same key per symbol in the new AST and joins
by equality. No pointers, no order.

### naja-if must persist

- per linked SNL object: its symbol's intrinsic key;
- a **slang version pin** (relink valid only for the dumping slang version);
- a **source fingerprint** (content hash of all SV files + flist + defines);
- the **source manifest** (file paths + flist + defines) so a consumer can
  re-elaborate. (naja-scope already keeps this in its sidecar — `load_spec`,
  `loaded_files`, session.py:127 — but a pure C++ binary needs it in naja-if.)

### Guards (fail-closed — this is the divergence safety)

- Relink **refuses** if the source fingerprint or slang version does not match
  what was stored. A wrong binding is worse than no binding; on mismatch, degrade
  to "intent not loaded", never best-effort bind to a drifted AST. With this, the
  relinked AST is provably the same design revision that produced the snapshot —
  the "one consistent view" property route-1 lost.
- **Dump-time self-check**: before writing keys, verify they are unique and
  round-trip against the live AST still in hand; fail the dump (or flag the
  object) on a collision, so a bad key never reaches disk.

### Contract & residual cases

- **The snapshot is no longer self-contained for intent**: cold relink requires
  the original source present at load time. A deployment shipping only a `.naja`
  with no source cannot relink → intent degrades cleanly to "not loaded".
- **Anonymous slang symbols** with no stable intrinsic key (unnamed blocks, some
  temporaries) get *no* intent rather than a guessed binding.

### Relink entry point (symmetric C++ / Python)

```cpp
// reads the persisted manifest from the loaded DB; optional source-root remap
bool SNLSVIntent::relink(const std::string& sourceRoot = "");
```
```python
naja.relink_intent(source_root=None) -> bool   # True if the bimap is now live
```

After a successful relink, `available()` is true and every Layer-1/2 call works as
warm. naja-scope's `intent.py` never learns which tier is live.

## Lowering-site construction (the bimap)

The exact correspondence exists only at lowering, where fan-out is in hand
(`cloneRTLInfos` at the uniquification clone site; the per-object
`annotateSourceInfo` site). Stamp `(SNLDesignObject* ↔ Symbol*)` there — a
path-only map collides at the 1→N points above. This is already implemented in
`SNLSVLiveASTLinkRegistry`; the new work extends it to also emit the **intrinsic
key** per object for the cold tier, alongside the existing `SNLSourceLoc`.

## Tests

- **C++ warm**: uniquified module instantiated N times — `snl_objects_of(body)`
  returns N distinct SNL designs; `ast_symbol_of` round-trips each back. A
  bit-blasted register — each FF primitive maps to the declaring variable symbol.
- **C++ Layer-1**: `typeOf(reg)` → enum members+encodings; `parametersOf(inst)` →
  localparam formula text + value; `packageMemberType(pkg, t)` → enum members.
- **Cold relink**: dump → reload (no Compilation) → `relink()` → assert the bimap
  matches the pre-dump bimap object-for-object (intrinsic keys join exactly across
  uniquification and bit-blasting). Mutate one source line → fingerprint mismatch →
  `relink()` returns false, `available()` stays false (fail-closed).
- **Python parity**: `naja.intent_type_of(reg)` (warm) == same after cold
  `relink_intent()`; matches the route-1 prototype's records on `intent_mini.sv`.

## Acceptance criteria

1. The slang-walking logic exists once in C++ (`SNLSVIntent`); the Python surface
   is a thin marshaler with no pybind/pyslang dependency.
2. Warm and cold (post-relink) produce identical bimaps and identical
   `intent_*` results, across uniquification (1→N) and bit-blasting (`#<id>`).
3. Relink is fail-closed on source/slang drift; the dump-time self-check catches
   key collisions before serialization.
4. No measurable change to lowering output; the key + bimap are additive.
5. Cold without source, or a najaeda without the link, degrades cleanly to
   "intent not loaded" — never a crash.

## Consuming side — what naja-scope does once this lands

- `intent.py` becomes a **thin, pyslang-free client**: resolve `ref → SNL object`
  (existing resolver — this is where `#<id>` support falls out, since `#2` already
  resolves to the FF instance), dispatch on `want`, call `naja.intent_type_of` /
  `intent_parameters_of` / `intent_package_member`, reshape into the `get_intent`
  response, degrade gracefully. The record-builders (`_type_record`,
  `_enum_members`, `_param_expr_text`, …) move **into C++** as Layer 1 — the
  prototype is their reference spec.
- `loader.py` passes `keep_ast_link=True` on SV load. `session.load_intent`
  becomes: warm → already live. "Available" means `naja.intent_available()`. Drop
  the separate `Driver`/`createCompilation` re-elaboration entirely. (The cold
  `naja.relink_intent()` branch is part of the **deferred** cold tier — until
  that gate is met, a cold snapshot session simply re-runs the SV load to go
  warm, which is now ~12–29s.)
- The optional `[intent]` pyslang dep is removed from `pyproject.toml`; the only
  requirement becomes a najaeda built with the link (`keep_ast_link` + `intent_*`).
- Cold start still returns "intent layer not loaded" until `relink_intent()`
  succeeds (already the implemented behavior).

See also `docs/naja-feature-request-sv-symbol-path.md` — the persistent-key FR,
now sharpened into the **intrinsic key** above (path alone is insufficient at
uniquification).
