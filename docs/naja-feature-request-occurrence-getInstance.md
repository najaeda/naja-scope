# Feature request prompt: `SNLOccurrence.getInstance()` / `isInstanceOccurrence()` in the naja Python bindings

> Hand this to a coding agent (or yourself) working in the naja C++ checkout at
> `/Users/xtof/WORK/naja3`. It adds a typed accessor (`getInstance()`, retrieval)
> and a matching predicate (`isInstanceOccurrence()`, discrimination) to
> `SNLOccurrence`, so an occurrence whose referenced object is an `SNLInstance`
> can be handled directly from Python — closing the only gap that forces
> `naja-scope` to parse `repr()` strings. Small, self-contained, mirrors
> accessors (`getInstTerm()`, `isNetComponentOccurrence()`) that already exist.

> **STATUS: IMPLEMENTED in najaeda 0.7.6** (local naja3 build). Both
> `SNLOccurrence.getInstance()` and `SNLOccurrence.isInstanceOccurrence()` are
> present and verified against `SNLLogicalCone` nodes; `naja-scope`'s `cone.py` /
> `snl.occurrence_leaf` now use `getInstance()` and the `repr()` parse is deleted.
> This doc is retained as the spec/record. Pending: PyPI release of 0.7.6.

---

## Problem

`SNLLogicalCone` (najaeda 0.7.6) returns its DAG nodes as
`(id, occurrence, kind, next_ids, prev_ids)` tuples
(`PySNLLogicalCone.cpp:140` `nodeToTuple`). For every node whose `kind` is
`Internal`, `Flop`, or `Blackbox`, the node's `SNLOccurrence` references an
**`SNLInstance`** (the leaf/internal cell crossed) — its `getPath()` is the path
to the instance's *parent*, and the object is the instance itself
(`SNLLogicalCone.cpp` builds these as `SNLOccurrence(path, instance)`).

But the Python `SNLOccurrence` exposes no way to get that instance. The binding
(`PySNLOccurrence.cpp:56-68`) wraps only:

- `getNetComponent()` → `dynamic_cast<SNLNetComponent*>(object_)`
- `getInstTerm()`     → `dynamic_cast<SNLInstTerm*>(object_)`
- `getPath()`

For an instance occurrence **both** `getNetComponent()` and `getInstTerm()`
return `None`, and there is no `getInstance()` and no bound `getObject()`. So a
Python consumer cannot recover the `SNLInstance` from a cone node — even though
the C++ `SNLOccurrence` plainly holds it in `object_`.

### Current `naja-scope` workaround (the thing to delete)

`naja-scope` reconstructs the instance by parsing the occurrence's `repr()`
string for the leaf name and re-looking it up in the parent design
(`src/naja_scope/snl.py`, `occurrence_tail_name` / `occurrence_leaf`):

```python
_OCC_REPR_RE = re.compile(r"<->0x[0-9a-fA-F]+\s+(.*)\]$")
def occurrence_tail_name(occ):           # parse repr -> last '/'-segment
    m = _OCC_REPR_RE.search(repr(occ)); s = m.group(1) if m else ""
    return s.rsplit("/", 1)[-1] if s else None
def occurrence_leaf(occ):
    ids = list(occ.getPath().getInstanceIDs())   # parent path only
    name = occurrence_tail_name(occ)
    leaf = node_from_ids(ids).design.getInstance(name)
    return leaf, ids + [leaf.getID()]
```

This is fragile: it depends on the exact `repr()` format
(`SNLOccurrence::getString('/')`, `SNLOccurrence.cpp:114`) and assumes instance
names never contain `/`. It should not exist.

## Task

Add two members to `SNLOccurrence`, mirroring the existing
`getInstTerm()`/`getNetComponent()` casters and the `isNetComponentOccurrence()`
predicate:

1. **Retrieval — `SNLInstance* SNLOccurrence::getInstance() const`** (returns the
   referenced object cast to `SNLInstance`, or `nullptr`); bound in Python as
   `SNLOccurrence.getInstance()` (the `SNLInstance`, or `None`). This is the one
   that removes naja-scope's workaround.
2. **Discrimination — `bool SNLOccurrence::isInstanceOccurrence() const`** (the
   sibling of `isNetComponentOccurrence()`, `SNLOccurrence.h:49`); bound as
   `SNLOccurrence.isInstanceOccurrence()`. Lets a generic occurrence consumer
   branch on type without probing every getter (a cone consumer already has the
   node `kind`, but other occurrence sources do not).

## Changes (mirror the existing casters precisely)

**1. `src/nl/netlist/snl/SNLOccurrence.h`**
- Forward-declare the class next to the others (`:11-17`):
  ```cpp
  class SNLInstance;
  ```
- Declare next to `getInstTerm()` / `getBitTerm()` (after `:58`):
  ```cpp
  /// \return the SNLInstance referenced by this SNLOccurrence if the object is a SNLInstance.
  SNLInstance* getInstance() const;
  ```
- Declare the predicate next to `isNetComponentOccurrence()` (after `:49`):
  ```cpp
  /// \return true if this SNLOccurrence references a SNLInstance.
  bool isInstanceOccurrence() const;
  ```

**2. `src/nl/netlist/snl/SNLOccurrence.cpp`**
- `#include "SNLInstance.h"` (alongside the existing includes, `:11-15`).
- Implement `getInstance()` next to `getInstTerm()` (`:90-92`), identical shape,
  and `isInstanceOccurrence()` next to `isNetComponentOccurrence()` (`:82-84`):
  ```cpp
  SNLInstance* SNLOccurrence::getInstance() const {
    return dynamic_cast<SNLInstance*>(getObject());
  }
  bool SNLOccurrence::isInstanceOccurrence() const {
    return dynamic_cast<SNLInstance*>(getObject()) != nullptr;
  }
  ```

**3. `src/nl/python/naja_wrapping/PySNLOccurrence.cpp`**
- `#include "PySNLInstance.h"` (next to `PySNLInstTerm.h`, `:11`).
- Add the generated accessors next to the existing casters (`:56-58`):
  ```cpp
  GetObjectMethod(SNLOccurrence, SNLInstance, getInstance)
  GetBoolAttribute(SNLOccurrence, isInstanceOccurrence)
  ```
  (`GetObjectMethod`, `PyInterface.h:344`, emits a `METH_NOARGS` function
  returning `PySNLInstance_Link(selfObject->getInstance())`, i.e. `None` on
  `nullptr` — same as the `SNLInstTerm`/`SNLInstance` pairing at
  `PySNLInstTerm.cpp:26`. `GetBoolAttribute`, `PyInterface.h:408`, emits the bool
  predicate.)
- Register both in `PySNLOccurrence_Methods[]` (`:60-68`):
  ```cpp
  { "getInstance", (PyCFunction)PySNLOccurrence_getInstance, METH_NOARGS,
    "get the SNLInstance of the SNLOccurrence (None if the object is not an instance)."},
  { "isInstanceOccurrence", (PyCFunction)PySNLOccurrence_isInstanceOccurrence, METH_NOARGS,
    "True if this SNLOccurrence references a SNLInstance."},
  ```

No CMake changes (no new files).

> As implemented in naja3 0.7.6 — `PySNLOccurrence.cpp:59,61` (`getInstance`,
> `isInstanceOccurrence`) and `:68,70` (method table) — exactly the above.

### Optional, while here (lower priority)
`SNLOccurrence::getString(char separator)` and `getBitTerm()` are also unbound.
Binding `getString()` would give consumers an *official* path string (instead of
relying on `repr()`), and `getBitTerm()` completes the caster set. Not required
for this request; `getInstance()` is the one that removes the workaround.

## Tests

- **C++** (`test/nl/snl/kernel/SNLOccurrenceTest.cpp`): for an occurrence built
  on an `SNLInstance`, assert `getInstance()` returns it and
  `getInstTerm()`/`getNetComponent()` return `nullptr`; for an inst-term
  occurrence assert `getInstance()` is `nullptr` and `getInstTerm()` is non-null.
- **Python** (`test/nl/python/naja_wrapping/test_snloccurrence.py`): same checks
  at the Python level. Plus a cone check: for a `SNLLogicalCone`, every node of
  kind `internal`/`flop`/`blackbox` has `occurrence.getInstance() is not None`
  and `.getInstance().getModel()` is usable; nodes of kind `root`/`ports` have
  `occurrence.getInstance() is None` (and `getNetComponent()` non-None).

## Acceptance criteria

1. New C++ and Python unit tests pass; existing `SNLOccurrence` tests unchanged.
2. `getInstance()` returns the instance for an instance occurrence and `None`
   for any non-instance occurrence; `getInstTerm()`/`getNetComponent()` behavior
   is unchanged.
3. For each `SNLLogicalCone` `internal`/`flop`/`blackbox` node, the node
   `occurrence.getInstance()` yields the crossed leaf `SNLInstance`.

## Consuming side (DONE in naja-scope)

`snl.occurrence_leaf` is now the repr-free form below;
`snl.occurrence_tail_name`, `_OCC_REPR_RE`, and `import re` are deleted:

```python
def occurrence_leaf(occ):
    inst = occ.getInstance()
    if inst is None:
        return None, None
    ids = list(occ.getPath().getInstanceIDs())   # parent path
    return inst, ids + [inst.getID()]
```

`cone.py` is otherwise unchanged. See `NAJAEDA_NOTES.md` feature request §6.
