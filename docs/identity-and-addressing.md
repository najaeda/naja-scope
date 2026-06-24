# Object identity & addressing in naja-scope

How naja-scope names, references, and round-trips netlist objects — the contract
behind every path string in a tool response. Grounded in naja's NLID /
`instanceID` model (verified on najaeda 0.7.6/0.7.7).

## Two questions, two identities

naja distinguishes two different "which object" questions, and so must we:

1. **Which database object** (model level) — *"the `state_q` net in the `serdiv`
   design"*. The canonical answer is the object's **`NLID`**: a composed unique id
   `(Type, DB, Library, Design, DesignObjectID, InstanceID, Bit)` — see naja's
   `NLID.h`. One object, one NLID; `NLUniverse.getObject(nlid)` resolves it back
   (najaeda 0.7.7).

2. **Which occurrence in the elaborated hierarchy** — *"the `state_q` flop inside
   `cva6.ex_stage_i.i_mult.i_div`"*. A design is instantiated many times, so a
   single model-level NLID is **not** enough. The canonical answer is a
   **hierarchical path**: the top design plus the chain of instances down to the
   object.

naja-scope is a hierarchy navigator, so its references are almost always the
second kind. **For hierarchy, an `instanceID` vector is the right identity.**

## The canonical hierarchical reference

```
( top-design NLID DesignReference )  +  ( vector of instanceIDs )  [ + leaf DesignObjectID ]
        (db, lib, design)                  getID() per level             term/net id
```

- **Root = the top design's NLID `DesignReference`** `(dbID, libraryID, designID)`,
  *not* its name. The name is a human alias; the `DesignReference` is the
  unambiguous global anchor. Resolve it with `NLUniverse.getSNLDesign((db, lib,
  design))`.
- **Path = an ordered vector of `instanceID`s**, each `SNLInstance.getID()`
  (unique within its parent design). Resolve one level with
  `SNLDesign.getInstanceByID(id)`; this is exactly `SNLPath.getInstanceIDs()` and
  what `SNLLogicalCone` / occurrences already hand back.
- **Leaf (for a term/net at the end)**: the object's own `DesignObjectID` in the
  final design (`getTermByID`, or a net by name).

Verified round-trip (UART fixture):

```python
ref  = (nid.getDBID(), nid.getLibraryID(), nid.getDesignID())  # top.getNLID() -> (1,0,0)
NLUniverse.get().getSNLDesign(ref)            # -> uart_top
ids  = [0, 12, 0]                             # u_tx -> u_div_cnt -> anonymous leaf
# walk getInstanceByID(id) per level  ->  u_tx . u_div_cnt . #0
```

## Display vs identity (why `#<id>` and `label` are different fields)

A tool response carries **both** an identity handle and a human-readable label:

- **`path`** — the identity, rendered as a dotted string. Each segment is the
  instance's **SV name** if it has one, else **`#<instanceID>`** for an anonymous
  lowered primitive (FF/gate). `#<id>` is literally `getID()`. This is what the
  agent passes back; resolution is name → `getInstance`, `#id` →
  `getInstanceByID` (`snl.instance_by_segment`).
- **`label`** — display only, derived lazily from the driven output net
  (`priv_lvl_q_dffrn`). Readable, **not unique, not an address**
  (`snl.friendly_label`). Never resolve a label; it exists so the agent can read
  *which* register a `#id` denotes.

This split is what let us delete the old O(netlist) eager naming pass: identity
comes free from `getID()`, and labels are computed only for the handful of
objects a response surfaces.

## Stability

`instanceID` (`getID`) and the top `DesignReference` are **stable across a naja-if
snapshot dump→reload** (verified) — so a `path` learned in one session resolves in
the next. `NLID`s are stable too. Names assigned by lowering are *not* relied on
for anonymous objects (there is no eager naming), so identity does not depend on
any naja-scope-side mutation of the netlist.

## NLID vs instanceID-vector — when to use which

| need | use |
|---|---|
| a single model-level DB object; a flat, hierarchy-free handle; a **net/term** identity (no clean per-level reverse lookup); a cross-DB key | **`NLID`** (`getNLID` / `getObject`, najaeda 0.7.7) |
| an object **in the elaborated hierarchy** (the common naja-scope case) | **top `DesignReference` + `instanceID` vector** (`getID` / `getInstanceByID`, najaeda 0.7.6) |

They compose: a hierarchical occurrence *is* `top DesignReference + instanceID
vector`. naja-scope's path scheme is built on the second row (works on 0.7.6); the
NLID class is the foundation for the first (net/term handles, flat keys) when we
need it.

## Where this lives in the code

- `snl.inst_segment(inst)` — `name or "#<id>"` (the addressable segment).
- `snl.instance_by_segment(design, seg)` — inverse: name → `getInstance`,
  `#id` → `getInstanceByID`.
- `snl.friendly_label(inst)` — lazy, display-only label from the driven net.
- `snl.node_from_ids` / `snl.path_str_from_ids` — build an `InstNode` / path from
  a top-rooted `instanceID` vector.
- `connectivity._leaf_entry`, `cone._leaf_record` — emit `{path, label, model,
  src}`; `cone._display_path` renders the label in place of a `#id` leaf for the
  cross-hierarchy affordance.
- `resolve.py` — walks a dotted path, each segment via `snl.child_node` →
  `instance_by_segment`.

## Open refinement

naja-scope currently renders the **root by the top design's name** because there
is one top design per process (DESIGN.md §1). The canonical identity anchors the
root on the top design's NLID `DesignReference`; capturing that `(db, lib,
design)` in the session (and resolving the root via `getSNLDesign`) would make the
root unambiguous if multi-top or multi-DB ever lands. Tracked here, not yet
implemented.
