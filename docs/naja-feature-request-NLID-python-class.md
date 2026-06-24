# Feature request prompt: a real `NLID` Python class + `NLUniverse.getObject(nlid)` reverse lookup

> Hand this to a coding agent (or yourself) working in the naja C++ checkout at
> `/Users/xtof/WORK/naja3`. It replaces the lossy 6-int list that `getNLID()`
> currently returns with a proper `naja.NLID` value class (carrying all 7 fields,
> including the dropped `Type`), and binds the existing C++ reverse lookup
> `NLUniverse::getObject(const NLID&)` to Python. Together they let a consumer
> (`naja-scope`) identify any SNL object by a stable, globally-unique, hashable,
> serializable key and resolve that key back to the object — replacing an
> O(netlist) Python naming pass with O(1) id lookups. Targets the 0.7.7 preview.

> **STATUS: REQUESTED.** As of the 0.7.7 preview build
> (`/Users/xtof/WORK/naja3/build/test/najaeda`, `getVersion()==0.7.7`),
> `getNLID()` is bound on all SNL objects but returns a **6-int list that omits
> the `Type` field** (`toPyNLID`, `PyInterface.h:105`), so a design, an instance
> with id 0, and a net with id 0 all serialize to the identical
> `[1,0,1,0,0,0]`. `NLUniverse::getObject` and any constructible `NLID` are not
> exposed. This request fixes all three.

---

## Problem

`naja-scope` (the agent-facing query layer over najaeda) must hand an object
reference to an LLM in a tool response, receive it back on a later call, and
re-resolve it to the same SNL object — **including across a naja-if snapshot
dump→reload**. Today it synthesizes stable *names* for the anonymous primitives
that SV lowering leaves unnamed (an O(netlist) Python pass, `ensure_names`),
purely to have an addressable key. The right primitive is naja's own stable id,
the `NLID`. Two gaps block that:

1. **`getNLID()` is lossy in Python.** `toPyNLID` (`PyInterface.h:105–117`) builds
   a **6**-element list:
   ```c
   [ dbID_, libraryID_, designID_, designObjectID_, instanceID_, bit_ ]
   ```
   but the C++ `NLID` (`NLID.h:30–36`) has **7** fields — the leading one is
   `Type` (`enum class Type: uint8_t {DB=1, Library, Design, Term, TermBit, Net,
   NetBit, Instance, InstTerm}`), and it is **dropped**. Verified collision on the
   UART fixture (design `uart_tx`, its instance #0, and its net `state` — three
   different objects):

   | object | C++ `type_` | emitted list |
   |---|---|---|
   | design `uart_tx` | `Design` | `[1,0,1,0,0,0]` |
   | net `state` (objID 0) | `Net` | `[1,0,1,0,0,0]` |
   | instance #0 (instID 0) | `Instance` | `[1,0,1,0,0,0]` |

   They differ **only** in the omitted `Type`, so the Python id is not unique.
   A bare list is also **mutable and unhashable** — unusable as a dict key / set
   member, which is exactly how a consumer uses an identity.

2. **No reverse lookup, no constructible `NLID`.** `NLUniverse::getObject(const
   NLID&)` exists in C++ (`NLUniverse.h:80`) but is **not bound**; and there is no
   `naja.NLID` a consumer can construct, so even a fixed 7-tuple can't be turned
   back into an `NLID` to hand to `getObject`.

## Task

1. **Add a `naja.NLID` Python value class** wrapping `naja::NL::NLID`, carrying all
   7 fields and mirroring the C++ value-object API.
2. **`getNLID()` on every SNL object returns an `naja.NLID`** (not the 6-int list).
   This subsumes the missing-`Type` bug — the object carries `Type` intrinsically.
3. **Bind `NLUniverse.getObject(nlid)`** → the wrapped concrete object (or `None`).

## Required Python surface (the consumer contract — `naja-scope` exercises these)

```python
from najaeda import naja

# 1. identity off any object (instance / net / term / design)
nid = some_instance.getNLID()              # -> naja.NLID

# 2. value semantics: hashable, comparable, printable
{nid: "label"}                             # usable as a dict key  -> needs __hash__
nid == other.getNLID()                     # __eq__/__ne__ (and __lt__ for ordering)
repr(nid); str(nid)                        # __repr__/__str__ (canonical, lossless)

# 3. fields + kind (so a consumer branches without decoding positions)
nid.getType()                              # int matching naja.NLID.Type
nid.getDBID(); nid.getLibraryID(); nid.getDesignID()
nid.getDesignObjectID(); nid.getInstanceID(); nid.getBit()
nid.isInstance(); nid.isNet(); nid.isTerm(); nid.isDesign()   # predicates
naja.NLID.Type.Instance                    # exposed enum (ints ok)

# 4. round-trip for the snapshot sidecar / agent wire — BOTH must hold:
naja.NLID(type, db, lib, design, designObjectID, instanceID, bit)  # 7-arg ctor
naja.NLID.from_string(str(nid)) == nid     # lossless text round-trip (recommended)

# 5. reverse lookup (universe-wide), resolving the concrete object
obj = naja.NLUniverse.get().getObject(nid) # -> SNLInstance | SNL*Net | SNL*Term | SNLDesign | None
```

The **must-haves** are: `__eq__`/`__hash__`/`__repr__`, the **7-arg constructor +
7 field accessors** (these alone make round-trip possible — serialize as the
7-tuple, reconstruct via the ctor), and `getObject`. `from_string`/`__str__` and
the `isInstance()/isNet()/...` predicates are strongly recommended (compact wire
form + readable branching) but secondary if the ctor+accessors exist.

## Changes (anchors in the naja3 tree)

**1. New `naja.NLID` wrapper — `src/nl/python/naja_wrapping/PyNLID.{h,cpp}` (new)**
- Wrap `naja::NL::NLID` (it is a small POD value, `NLID.h:30`). Mirror:
  - the full constructor `NLID(Type, DBID, LibraryID, DesignID, DesignObjectID id,
    DesignObjectID instanceID, Bit bit)` (`NLID.h:247`) as `tp_init` /
    `__new__` taking 7 ints (accept an int for `Type`);
  - `operator<,<=,==,!=,>,>=` (`NLID.h:257–282`) → `tp_richcompare`;
  - `getString()` (`NLID.h:289`) → `tp_repr`/`tp_str` (a lossless, parseable form —
    if the current `"[Type: …]"` text is kept, add a matching parser; a compact
    `"t:db:lib:design:objid:instid:bit"` is preferred);
  - `tp_hash` over all 7 fields (consistent with `__eq__`);
  - field getters reading `type_, dbID_, libraryID_, designID_, designObjectID_,
    instanceID_, bit_`; predicates over `type_`;
  - expose the `Type` enum (`NLID.h:31`) as `naja.NLID.Type` (or module ints).
- Register the type in the module init alongside the other Py types.

**2. `getNLID()` returns `NLID` — `PyInterface.h`**
- Change `toPyNLID` (`PyInterface.h:105–117`) to return `PyNLID_Link(id)` (the new
  wrapper) instead of the 6-int list. The generic `DirectGetNLIDMethod` macro
  (`PyInterface.h:211–214`) and the per-class `PySNLDesign_getNLID`
  (`PySNLDesign.cpp:505`) then yield the class everywhere with no further change.
- If a list/tuple form is still wanted, expose it as `NLID.toTuple()` — do **not**
  keep returning a bare list from `getNLID()`.

**3. Bind `NLUniverse.getObject` — `src/nl/python/naja_wrapping/PyNLUniverse.cpp`**
- Mirror `pyNLUniverse_getSNLDesign` (`PyNLUniverse.cpp:195–228`), which already
  parses an arg and dispatches; here parse one `PyNLID` arg, call
  `selfObject->getObject(*nlid)` (`NLUniverse.h:80`), and wrap the returned
  `NLObject*` to its concrete Python type. Register in `PyNLUniverse_Methods[]`
  (`PyNLUniverse.cpp:241`) as `METH_O`.
- **Wrapping the polymorphic return** is the one non-mechanical part: `getObject`
  returns `NLObject*`. Dispatch to the concrete `Py…_Link` (`PyInterface.h:331`):
  branch on `nlid.getType()` (cleanest — `Instance`→`PySNLInstance_Link`,
  `Net`/`NetBit`→`PySNLScalarNet_Link`/`PySNLBusNetBit_Link`,
  `Term`/`TermBit`/`InstTerm`→the term/instterm links, `Design`→`PySNLDesign_Link`),
  or `dynamic_cast` cascade. Return `Py_None` for an unresolved/unhandled id.
  (The typed siblings `getInstTerm`/`getBusTermBit`/`getBusNetBit` at
  `NLUniverse.h:74–79` can back the term/net-bit branches.)

## Tests

- **C++** (`test/nl/python/naja_wrapping/` + a kernel test): for one instance, one
  scalar net, one bus-net bit, one term, and the containing design, assert their
  `getNLID()`s are **pairwise distinct** (this is the regression for the dropped
  `Type` — instance #0, net #0 and the design must differ), and that
  `getObject(getNLID())` returns the same object for each.
- **Python** (`test/.../test_nlid.py`):
  1. `o.getNLID()` is an `naja.NLID`; usable as a dict key; `==`/`!=`/`<` and
     `hash` behave; `repr`/`str` are stable.
  2. `naja.NLID(*sevenInts)` reconstructs an equal id;
     `NLID.from_string(str(nid)) == nid`.
  3. `getObject(nid)` round-trips an instance, a net, and a term to the same
     object (by name/identity).
  4. **Snapshot round-trip**: capture `{name: nid}` for instances *and* nets;
     `dumpNajaIF` → reset → `loadNajaIF`; assert every `getNLID()` is unchanged and
     `getObject` still resolves. (This currently "passes" only vacuously because
     all ids collide — it must pass with *distinct* ids.)

## Acceptance criteria

1. `getNLID()` returns `naja.NLID` on instance / net / net-bit / term / design;
   a design, an instance with id 0, and a net with id 0 have **distinct** NLIDs.
2. `naja.NLID` is hashable, ordered, printable, constructible from 7 ints, and
   round-trips losslessly (`from_string(str(x)) == x` and/or `NLID(*x.toTuple())
   == x`).
3. `NLUniverse.get().getObject(nlid)` returns the concrete wrapped object for
   instance / net / term / design ids and `None` for an unknown id.
4. All four hold after a naja-if dump→reload. Existing tests unchanged.

## Consuming side (what `naja-scope` does once this lands)

- **Delete `ensure_names`** (`src/naja_scope/naming.py`) and its calls at load and
  snapshot-reload (`session.py:65`, `session.py:114`). The O(netlist) Python pass
  on both the cold-load and reload paths goes away.
- Key every object on its `NLID`; reverse-resolve agent-supplied references with
  `getObject`. Nets/terms fall out for free (they now carry a unique `NLID`); no
  more order-dependent `n_<id>` net naming.
- Derive the friendly `tx_o_dff`-style label **lazily**, only for the handful of
  objects a response surfaces (display only; the round-trip handle is the NLID).
- Hierarchical instance addressing can keep using `getID()` + `getInstanceByID()`
  (already snapshot-stable); the `NLID` class is the internal identity key and the
  flat reverse-lookup handle for nets/terms. See `docs/phase2-plan.md` context and
  `eval/RESULTS.md` for why this matters (cold-load decomposition: naja
  elaboration ~46–50s; the rest was this Python pass).
