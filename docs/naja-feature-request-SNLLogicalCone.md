# Feature request prompt: `SNLLogicalCone` in the naja C++ SNL layer

> Hand this to a coding agent (or yourself) working in the naja C++ checkout at
> `/Users/xtof/WORK/naja2`. It specifies a new C++ class that pushes logical-cone
> tracing (fan-in / fan-out, stop-at-flops) below the Python boundary. Today this
> is done in Python in the `naja-scope` repo (`src/naja_scope/cone.py`) by calling
> `SNLEquipotential` once per frontier net and recursing in Python — one
> pybind round-trip and one `std::set`→Python materialization per net, which on
> CVA6-class designs dominates the cost. Doing the whole BFS in C++ and returning
> only the result collapses that to a single boundary crossing.

---

## Task

Add a `naja::NL::SNLLogicalCone` class to the SNL kernel that computes the
logical fan-in or fan-out cone of a starting net-component occurrence and **stores
it as a rooted DAG that lives in the object** — nodes are the leaf cells crossed,
edges are their combinatorial dependencies, the root is the start pin, and the
leaves are the barriers (flops / ports / black boxes) with O(1) access. Expose it
through the najaeda Python bindings.

It is the multi-level generalization of the existing `SNLEquipotential`:
`SNLEquipotential` walks one logical net (across hierarchy) and returns the leaf
inst-term occurrences and top terms on it; `SNLLogicalCone` repeatedly builds
equipotentials and crosses *through* the leaf cells it lands on **following
combinatorial arcs only**, until it reaches a sequential barrier (a flip-flop pin
— the Q output on a fan-in walk, the D input on a fan-out walk), a top-level
port, or an unmodeled black box (which is opaque, so the walk stops at its pin).
The cone is the purely combinatorial logic between sequential elements, the
design boundary, and any opaque cells.

Because a flip-flop's D→Q arc is *not* a combinatorial arc, "cross only
combinatorial arcs" and "stop at flops" are the same rule: the walk arrives at a
flop pin and finds no combinatorial arc to continue through. There is no
node/depth cap and no separate stop mode — the sequential/port barrier is
intrinsic to the cone's definition. (Crossing flops to build a register-to-
register *sequential* cone is a different tool and is out of scope here.)

## Where it lives (match existing conventions)

- Kernel class: `src/nl/netlist/snl/SNLLogicalCone.h` + `.cpp`, in namespace
  `naja::NL`. Model the file structure, copyright header, and the private
  extractor-struct idiom directly on
  `src/nl/netlist/snl/SNLEquipotential.{h,cpp}`.
- Add the `.cpp` to the kernel target (same `CMakeLists.txt` /
  `target_sources` list that already names `SNLEquipotential.cpp` under
  `src/nl/netlist/`).
- Python wrapping: `src/nl/python/naja_wrapping/PySNLLogicalCone.{h,cpp}`,
  registered in that directory's `CMakeLists.txt` and in the module init
  alongside `PySNLEquipotential`. Mirror `PySNLEquipotential.cpp` exactly for the
  object protocol, deallocator, and `NajaCollection`→Python iterator pattern.
- Tests: `test/nl/snl/kernel/SNLLogicalConeTest0.cpp` (GoogleTest, mirror
  `SNLEquipotentialTest0.cpp`) and a Python test
  `test/nl/python/naja_wrapping/test_snllogicalcone.py` (mirror
  `test_snlequipotential.py`).
- Docs: add `src/najaeda/najaeda/docs/source/logicalcone.rst` mirroring
  `equipotential.rst`.

## Building blocks that already exist (reuse, do not re-implement)

- `SNLEquipotential(const SNLOccurrence& netComponentOccurrence)` — give it a
  net-component occurrence (a `SNLBitTerm`/`SNLInstTerm` at a path) and it returns:
  - `getInstTermOccurrences()` → `NajaCollection<SNLOccurrence>`: the **leaf**
    inst-term occurrences electrically on this net (each occurrence's object is a
    `SNLInstTerm`, its path is the path to the owning instance's parent).
  - `getTerms()` → `NajaCollection<SNLBitTerm*>`: top-level design terms on the
    net (the design boundary).
- `SNLOccurrence` — `(SNLPath, SNLDesignObject*)`; comparable / hashable-by-order
  (usable as `std::set` key, as `SNLEquipotential` already does for its visited
  set). Use it as the node and visited identity here too.
- `SNLPath` — `SNLPath(headPath, SNLInstance*)` extends a path; `getHeadPath()`,
  `getTailInstance()`, `getInstanceIDs()`, `size()`, `empty()`.
- `SNLInstTerm` — `getInstance()`, `getBitTerm()`, `getDirection()`.
- `SNLInstance::isLeaf()` / `SNLDesign::isLeaf()` (`isBlackBox() || isPrimitive()`).
- **Combinatorial arcs — the gate-crossing rule** (`SNLDesignModeling`,
  `src/nl/netlist/decorators/SNLDesignModeling.h`):
  - `getCombinatorialInputs(SNLInstTerm* output)` →
    `NajaCollection<SNLInstTerm*>`: the same-instance input pins that drive this
    output through a combinatorial arc. Use this to cross a cell on a **fan-in**
    walk (you arrived at the cell's driving output; continue only from the inputs
    that combinationally feed it).
  - `getCombinatorialOutputs(SNLInstTerm* input)` → the same-instance output pins
    this input combinationally drives. Use this to cross a cell on a **fan-out**
    walk.
  - On a flip-flop these return empty for the D↔Q pair (D→Q is a sequential, not
    combinatorial, arc), so the walk stops there automatically.
  - `hasModeling(design)` / `areDependenciesDefined(const SNLBitTerm*)` — whether
    arc info exists for the cell. A leaf with no modeling is an opaque black box:
    the walk stops at it (`Blackbox` frontier), it is not crossed. See the
    algorithm.
- **Sequential test**: `SNLDesignModeling::isSequential(design)` (what the Python
  `SNLDesign.isSequential()` binds to — see `PySNLDesign.cpp:563`). Use it to tag
  a barrier node as a `Flop` leaf.
- `SNLNetComponent::Direction` (`Input` / `Output` / `InOut`).
- `NajaCollection` + `NajaSTLCollection` for returning sets to Python.

## Algorithm

`naja-scope/src/naja_scope/cone.py` is the structural reference for the
BFS-over-equipotentials shape, **but this class corrects its gate-crossing**:
`cone.py` recurses through *every* opposite-direction term of a driver cell,
which over-approximates multi-output cells and relies on `stopAtFlops` to halt.
Here, crossing follows `SNLDesignModeling` combinatorial arcs, which is both more
precise and self-terminating at sequential pins.

### The result is a DAG owned by the object

`SNLLogicalCone` builds and stores a **rooted directed acyclic graph**, not a flat
set. Construct it once; the object owns it for its lifetime and exposes O(1)
access to the pieces callers need:
- **Nodes** — a contiguous `std::vector<Node>` indexed by `NodeID` (cache-friendly,
  index-based adjacency). One node per distinct leaf-cell occurrence in the cone,
  deduplicated, so a cell reached by two paths is a single shared node (true DAG,
  not a tree).
- **Edges** — index adjacency on each node, in *signal-flow / cone-outward*
  direction: `next` points one combinatorial step further from the root (FanIn:
  toward the driving sources; FanOut: toward the driven sinks); `prev` is the
  reverse, free to fill while building, so paths can be walked either way.
- **Root** — the single start pin. A cone is always rooted at **one bit**: the
  start `SNLOccurrence` is a single-bit net component (a scalar term/net or one
  bit of a bus). A caller wanting a bus cone builds one `SNLLogicalCone` per bit.
- **Leaves** — the frontier: every `Flop` / `Ports` / `Blackbox` node. Recorded
  into a `leaves_` vector at creation time, so `getLeaves()` is O(1) with no
  re-scan — this is the "fast access to leaves" requirement.

Per-direction roles (shown for `FanIn` — tracing what drives the start; mirror by
swapping Input↔Output and `getCombinatorialInputs`↔`getCombinatorialOutputs` for
`FanOut`):
- On each equipotential, the leaf pin of interest is the **driver**: the
  inst-term whose direction is `Output`. (For `FanOut` it is the **load**: the
  `Input` inst-term.) Skip the others.
- Cross that cell using `getCombinatorialInputs(driverOutput)` — the input pins
  combinationally feeding *that* output — and continue from each such input's net.
  (For `FanOut`: `getCombinatorialOutputs(loadInput)`.)
- A top-level term on the equipotential that is a primary **input** is a `Ports`
  leaf. (For `FanOut`: a top **output**.)

BFS construction (each popped item carries the *parent node* whose input net we
are resolving, so every driver/port we find becomes an edge `parent → child`):

```
nodes:   vector<Node>                       # index == NodeID
indexOf: map<SNLOccurrence, NodeID>         # dedup -> shared DAG nodes
leaves:  vector<NodeID>
expanded: set<NodeID>                        # internal nodes already walked through

getOrCreate(occ, kind) -> NodeID:
    if occ in indexOf: return indexOf[occ]
    id = nodes.size(); nodes.push({occ, kind}); indexOf[occ] = id
    if kind in {Flop, Ports, Blackbox}: leaves.push(id)
    return id

addEdge(parentId, childId):                  # cone-outward
    nodes[parentId].next += childId          # (dedup edges)
    nodes[childId].prev  += parentId

# seed: the single start bit is the Root node (id 0); explore its net
rootId = getOrCreate(start, Root)            # start is one bit
queue.push_back( (rootId, start) )           # (parent node, net-component occurrence)

while queue not empty:
    (parentId, netOcc) = queue.pop_front()
    eq = SNLEquipotential(netOcc)
    for occ in eq.getInstTermOccurrences():
        instTerm = occ.getObject() as SNLInstTerm
        if instTerm.getDirection() != driverDir: continue   # FanIn: Output / FanOut: Input
        inst  = instTerm.getInstance()
        model = inst.getModel()
        instOcc = SNLOccurrence(occ.getPath(), inst)

        # classify the cell -> node kind
        if   isSequential(model):  kind = Flop        # FanIn=Q, FanOut=D barrier
        elif not hasModeling(model): kind = Blackbox  # opaque cell, do not cross
        else:                        kind = Internal

        childId = getOrCreate(instOcc, kind)
        addEdge(parentId, childId)
        if kind != Internal:  continue                # leaf: stop
        if childId in expanded: continue              # DAG sharing: walk a node once
        expanded.insert(childId)

        crossed = (FanIn) ? getCombinatorialInputs(instTerm)
                          : getCombinatorialOutputs(instTerm)   # same-instance pins
        for nextInstTerm in crossed:
            queue.push_back( (childId, SNLOccurrence(occ.getPath(), nextInstTerm.getBitTerm())) )
        # crossed may be legitimately empty (const/tie cell) — that node is a sink.

    for term in eq.getTerms():                        # top design terms on this net
        if term.getDirection() == portDir:            # FanIn: PI / FanOut: PO
            portId = getOrCreate(SNLOccurrence(netOcc.getPath(), term), Ports)
            addEdge(parentId, portId)
```

The DAG is built to completion — no node/depth cap, no `truncated` flag. A
combinatorial cone bounded by sequential pins, ports, and opaque black boxes is
finite and acyclic; `expanded` guarantees each internal node is walked once (and
guards the rare combinational loop). Any token/size bounding of the *response* is
the caller's job (`naja-scope` bounds it when serializing the DAG), not this
class's.

**Unmodeled cells = barriers.** Combinatorial-arc crossing needs modeling. The
naja-lowered primitives that make up these designs all have it (`hasModeling` is
true), so they cross normally. A leaf cell with **no** modeling is an opaque black
box: stop at the cell you reached and record it as a `Blackbox` leaf node — do not
cross it (neither through its arcs, which are undefined, nor by falling back to
all its pins). The black box is a real boundary of what the cone can know, and
the caller should see it as one.

Notes:
- Node identity is the instance occurrence (`indexOf`), so shared logic collapses
  to one node and the result is a DAG, not a tree. `expanded` (node ids already
  walked through) prevents re-expansion, analogous to how `SNLEquipotential`'s
  extractor dedups net occurrences.
- De-duplicate edges (a `parent → child` pair can be discovered twice); a small
  per-node check or a `set` while building is enough.
- Use a FIFO queue (BFS). Order is not required for correctness, but BFS lays out
  nodes roughly by distance from the root, which is convenient when the caller
  presents a bounded view of a large cone.

## Proposed public API

```cpp
namespace naja::NL {

class SNLLogicalCone {
 public:
  enum class Direction { FanIn, FanOut };

  using NodeID = uint32_t;
  // Root:     a start pin (term occurrence) — the cone's apex.
  // Internal: a combinatorial leaf cell the walk crossed.
  // Flop:     a sequential barrier (FanIn = a flop Q, FanOut = a flop D).
  // Ports:    a top-level boundary port (FanIn = primary input, FanOut = primary output).
  // Blackbox: a leaf cell with no arc modeling — opaque, the walk stops at its pin.
  // Flop/Ports/Blackbox are the cone leaves.
  enum class NodeKind { Root, Internal, Flop, Ports, Blackbox };

  struct Node {
    SNLOccurrence       occurrence;  // instance occ (Internal/Flop/Blackbox); term occ (Root/Ports)
    NodeKind            kind;
    std::vector<NodeID> next;        // edges cone-outward (toward leaves)
    std::vector<NodeID> prev;        // edges cone-inward  (toward root); reverse of next
  };

  // A cone is rooted at one bit: `start` is a single-bit net-component
  // occurrence. Direction is the only other knob: the sequential/port/blackbox
  // barrier is intrinsic.
  SNLLogicalCone(const SNLOccurrence& start, Direction direction);

  Direction getDirection() const;

  // The DAG. nodes[id] is addressed by NodeID; root and leaves index into it.
  const std::vector<Node>&   getNodes()  const;   // whole graph
  NodeID                     getRoot()   const;   // the single start-bit node — the apex
  const std::vector<NodeID>& getLeaves() const;   // O(1): the frontier (Flop/Ports/Blackbox)

  size_t getNodeCount() const;
  // counts of cone leaf cells by model name (for counts_by_model)
  const std::map<std::string, size_t>& getCountsByModel() const;
};

}  // namespace naja::NL
```

`getLeaves()` is the affordance the cross-hierarchy question needs: each leaf
`Node` carries its `occurrence` (full hierarchical path) and `kind`, so the caller
reads the frontier directly. The full DAG (`getNodes()` + `next`/`prev`) is there
when a caller wants to trace or visualize a path from a leaf back to the root, but
nothing forces it to walk the whole graph.

Keep the **hierarchy grouping** (`frontier_summary`: group leaves by top-level
submodule, flag registers outside the root's subtree) **out of C++** — it is an
O(leaves) string operation that stays cheap in `naja-scope` Python. C++ owns the
DAG; `cone.py` drops its per-net `build_equipotential` loop, calls this once, and
groups `getLeaves()`.

## Python binding surface (what `naja-scope` will call)

A `naja.SNLLogicalCone(start_occurrence, direction=...)` returning an object that
exposes the DAG:
- `.get_leaves()` — the frontier, what `cone.py` consumes first: each yields its
  `occurrence` and `kind`, the `kind` mapping to the `"flop" | "ports" |
  "blackbox"` strings `cone.py` uses.
- `.get_root()` — the single start-bit node (the apex).
- `.get_nodes()` / node `.next` / `.prev` (or a `.get_edges()` pair list) — the
  full graph, for callers that trace or visualize a root↔leaf path. `naja-scope`
  serializes this only on request, keeping the default MCP response lean.
- `.get_counts_by_model()`.

Mirror `PySNLEquipotential.cpp` for the object protocol; a `Node`/`NodeKind` needs
a small Python view (a tuple `(occurrence, kind, next_ids, prev_ids)` is enough)
plus the `NajaCollection`→iterator pattern for the node/leaf/root collections.

## Acceptance criteria

1. Kernel + Python unit tests pass (build with the project's normal CMake flow;
   run the SNL kernel gtests and the najaeda python tests).
2. On a small structural fixture with a known FF feeding combinational logic, a
   fan-in cone from a downstream single-bit pin yields a DAG whose `getRoot()` is
   that start bit, whose `getLeaves()` contains the upstream FF's Q as a `Flop`
   leaf, and whose internal nodes are the gates between — connected by
   `next`/`prev` edges from root to leaf. A fan-out cone from the FF's Q reaches
   downstream FF D pins as `Flop` leaves and any primary outputs as `Ports`.
3. **DAG shape is correct**: reconvergent logic (one cell feeding two downstream
   cells that meet again) produces a single shared node with multiple `prev`/`next`
   edges — not duplicated subtrees; `getRoot()`→`next`* reaches exactly
   `getLeaves()`; the graph is acyclic.
4. **Combinatorial-arc crossing is honored**, not all-pins recursion: on a
   multi-output leaf cell, a fan-in walk that arrives at one output follows only
   the inputs combinationally feeding *that* output (verify against the cell's
   `getCombinatorialInputs`); the D→Q pair of a flop is never crossed.
5. **Unmodeled black box is a barrier**: a fan-in walk that reaches an instance of
   a black box with no modeling (`hasModeling(model)` false) records it as a
   `Blackbox` leaf and does not traverse into or across it.
6. Result parity with the current Python `cone.py` on the CVA6 cross-hierarchy
   case: fan-in cone of `cva6.ex_stage_i.i_mult.i_div.state_d` has leaves in
   `csr_regfile_i` and `issue_stage_i.i_scoreboard` (the golden for `naja-scope`
   eval `cva6-div-cone-crosshier`). The C++ leaf set should match the Python BFS
   for single-output primitives and be a strict subset where the old code
   over-approximated multi-output cells — and be faster.
7. No behavior change to `SNLEquipotential` (reused as-is).

## Why this is the right layer

`SNLEquipotential` already proves the pattern: a self-contained traversal struct
over occurrences/paths that returns sets to Python in one shot. The cone is the
same shape one level up. Moving it into C++ removes N pybind round-trips and N
set materializations per query (N = number of nets in the cone), which is the
actual hotspot on large cores — not the per-net walk, which is already C++.

---

## Follow-up (2026-06-22): shipped in najaeda 0.7.5 but **fails AC 5 & 6** — gate primitives have no modeling

`naja.SNLLogicalCone` shipped in najaeda 0.7.5 with the API this document
specifies (`SNLLogicalCone(occurrence, FanIn|FanOut)`; `get_nodes()` returning
`(id, occurrence, kind, next_ids, prev_ids)`; `get_leaves()`, `get_root()`,
`get_node_count()`, `get_direction()`; node kinds `root`/`internal`/`flop`/
`ports`/`blackbox`). The DAG model, hierarchy crossing, and flop/port barriers
all work as designed.

**But the "unmodeled cells = barriers" rule (Algorithm §, AC 5) bites a case
this document assumed away.** It states: *"The naja-lowered primitives that make
up these designs all have it (`hasModeling` is true), so they cross normally."*
That assumption is false. Verified against najaeda 0.7.5 on the
`cv32a6_imac_sv32` snapshot (`naja-scope` `eval/.cache/cva6-small`):

- `assign` and `naja_mux2__w*` have `hasModeling()==True` → crossed (`internal`).
- The combinational **gate** primitives SV lowering emits — `and_2`, `or_2`,
  `not_1`, `and_3`, `and_5`, `and_8`, … — have a `getTruthTable()` but
  `hasModeling()==False`. The cone classifies each as `blackbox` and **stops**.

Because real combinational paths run through and/or/not gates, the cone
terminates almost immediately. Fan-in of
`cva6.ex_stage_i.i_mult.i_div.state_d`:

| | nodes/bit | flop frontier | outside ex_stage |
|---|---|---|---|
| `SNLLogicalCone` 0.7.5 | 83 | 2 | **none** |
| hand-rolled equipotential `cone.py` (verified truth) | 491 total | 16 | csr_regfile_i, issue_stage_i, cache |

This directly **violates acceptance criterion 6** (the `state_d` fan-in cone must
have leaves in `csr_regfile_i` and `issue_stage_i.i_scoreboard`) and the spirit
of **criterion 5** (only genuinely unmodeled black boxes should be barriers —
truth-table-bearing logic gates are not black boxes, they are just missing arc
metadata).

**Fix — one of:**
1. **Lowering sets the arcs.** `SNLSVConstructor` already calls `setTruthTable`
   on these gate primitives; have it also call `addCombinatorialArcs(inputs,
   outputs)` (all inputs → the output) the way it evidently does for assign/mux,
   so `hasModeling()` is true for every comb primitive it emits.
2. **The cone derives crossing from the truth table.** When `hasModeling()` is
   absent but `getTruthTable()` is present on a single-output comb leaf, treat
   all inputs as combinatorially feeding the output instead of declaring a
   `blackbox`. (Reserve `blackbox` for cells with neither modeling nor a truth
   table.)

Confirmed that injecting the arcs from Python (`model.addCombinatorialArcs(...)`
on each gate model) does make the cone traverse them — so the algorithm is
sound; only the per-cell modeling is missing. `naja-scope` does **not** ship that
injection (it mutates the shared primitives library and the partial result
diverges ~3–7× from the verified equipotential frontier, needing reconciliation).

**Status: RESOLVED in naja3 / "future 0.7.6"** — HEAD `4e557f5d "Add
Combinatorial Dependencies to NLDB0 and, or, xor, ... gates"` adds modeling to
the lowered gate primitives, so the cone crosses them. `naja-scope`'s `cone.py`
has been rewritten entirely onto `SNLLogicalCone` (the equipotential BFS is
gone); the `state_d` fan-in cone now reaches the cross-hier frontier
(`csr_regfile_i.priv_lvl_q`, `issue_stage_i.i_scoreboard`). Two follow-ups remain
(NAJAEDA_NOTES.md §6–7): (a) expose a cone node's `SNLInstance` directly so
consumers don't parse `repr()` for the leaf name; (b) reconcile why the native
frontier is ~12× larger than the old equipotential one (196 vs 16 flops on
state_d) — real combinational fanin vs over-broad arcs on multi-output cells.
