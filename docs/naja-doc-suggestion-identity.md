# Doc suggestion for naja: identification & hierarchical addressing

> Suggested additions to `naja3/docs/snl/identification.rst` (or a new
> `hierarchical-addressing.rst` linked from it). The current page documents the
> flat `NLID` well; what's missing is (1) the `Type` enum values, (2) the
> **model-level NLID vs. hierarchical occurrence** distinction — the one thing a
> consumer most needs and most easily gets wrong — (3) the access/reverse-lookup
> APIs, and (4) the Python `NLID` class. All snippets below are verified against
> najaeda 0.7.7. Written from the naja-scope consumer's perspective: this is the
> mental model we had to reconstruct empirically; documenting it saves the next
> consumer that work.

## 1. Enumerate the `Type` field (it's the disambiguator)

The field table lists "Object type | 0-255" but not the values. The `Type`
enum is what makes a design, an instance, and a net with the same ids distinct —
worth spelling out:

```rst
``Type`` is ``NLID::Type`` (``NLID.h``):
``DB=1, Library, Design, Term, TermBit, Net, NetBit, Instance, InstTerm``.
Two objects in the same design with the same numeric id but different ``Type``
(e.g. instance #0 vs net #0) are distinct objects; ``Type`` is the discriminator.
```

## 2. Model-level identity vs. hierarchical occurrence (the key addition)

```rst
Two identity questions
~~~~~~~~~~~~~~~~~~~~~~~~

NLID answers *"which database object"* — a **model-level** identity. A design is
instantiated many times, so an ``NLID`` alone does **not** locate a specific
occurrence in the elaborated hierarchy.

To identify an object **in the hierarchy**, compose:

* the **top design** as an ``NLID::DesignReference`` ``(dbID, libraryID,
  designID)`` — the unambiguous anchor (a design *name* is only a convenience);
* a **vector of instance ids** (``SNLInstance::getID()``, unique within each
  parent design), one per level down the hierarchy — this is exactly
  ``SNLPath::getInstanceIDs()``;
* optionally a leaf ``DesignObjectID`` for a terminal net/term.

``SNLOccurrence`` is the in-memory form of this (an ``SNLPath`` + the object).
The id vector and the ``DesignReference`` are **stable across a naja-if
dump/reload**, so they can be persisted and resolved in a later session.
```

## 3. Show the access / reverse-lookup APIs

The page says NLIDs "access objects from SNLUniverse" but shows no call. Add:

```rst
Resolving identities
~~~~~~~~~~~~~~~~~~~~~~

* ``NLUniverse::getObject(const NLID&)`` — any object from its (model-level) NLID.
* ``NLUniverse::getSNLDesign(DesignReference)`` — a design from ``(db, lib,
  design)``; the root of a hierarchical path.
* ``SNLDesign::getInstanceByID(id)`` / ``getInstanceByIDList(ids)`` /
  ``getTermByID(id)`` — resolve one level of a hierarchical path, or a terminal.
```

```python
# Hierarchical resolution from (top DesignReference + instance-id vector):
ref    = (nid.getDBID(), nid.getLibraryID(), nid.getDesignID())   # top.getNLID()
design = NLUniverse.get().getSNLDesign(ref)
for i in id_vector:                       # e.g. [0, 12, 0]
    inst   = design.getInstanceByID(i)
    design = inst.getModel()
```

## 4. Document the Python `NLID` class (najaeda 0.7.7)

```rst
Python ``NLID``
~~~~~~~~~~~~~~~

``object.getNLID()`` returns an ``naja.NLID`` value object:

* comparable / hashable / printable (``==``, ``<``, ``hash()``, ``repr`` =
  ``NLID(type:db:lib:design:objID:instID:bit)``) — usable as a dict/set key;
* fields: ``getType()``, ``getDBID()``, ``getLibraryID()``, ``getDesignID()``,
  ``getDesignObjectID()``, ``getInstanceID()``, ``getBit()``;
* predicates: ``isDesign()``, ``isInstance()``, ``isNet()``, ``isTerm()``;
* the ``NLID.Type`` enum (``NLID.Instance`` …);
* round-trip: ``naja.NLID(*7ints)`` and ``NLID.from_string(str(nid))`` /
  ``nid.toTuple()`` reconstruct an equal id.
```

## 5. Optional: a one-line guidance note

```rst
.. note::
   Use an ``NLID`` for a single model-level object or a flat handle; use a
   ``DesignReference`` + instance-id vector for an object **in the elaborated
   hierarchy**. The two compose: an occurrence is a top ``DesignReference`` plus
   an instance-id chain.
```

---

*Naming nit:* the prose elsewhere occasionally referred to a `getSNLID` accessor;
the actual method is `getNLID()`. (The `identification.rst` page is already
correct.)
