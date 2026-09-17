# Inspect Designs In A Live Python Or Jupyter Session

The binding runs existing MCP inspection tools inside the process that owns the
Naja universe. It does not load, copy, dump, edit, or take ownership of designs.
Use the same installed Naja-Scope version in the owner and MCP server.

## Start In The Owner

After loading your designs using the raw `from najaeda import naja` API,
start a bridge in that same interpreter:

```python
from naja_scope.binding import SessionBridge

# existing_design_a and existing_design_b are raw naja.SNLDesign objects.
# shared_lock is the existing threading.RLock used by every editor/verifier.
scope = SessionBridge(lock=shared_lock, source_files=source_files).start()
golden_ref = scope.design_reference(existing_design_a)
edited_ref = scope.design_reference(existing_design_b)
connection_file = str(scope.connection_file)
```

If no other component has a lock, omit `lock=` and hold `scope.lock` around
every edit, load, top-selection change, and destruction. The bridge must share
the *exact same lock object* as any other in-process verifier or editor.
For a Kepler MCP bridge this can be its public `lock`, passed to `SessionBridge`.
Naja-Scope does not import or require Kepler or 22b.

`source_files` is an optional sequence of paths used to resolve relative source
locations. It does not reload RTL. The warm native AST/intent link is reused if
available; attachment never re-elaborates a design to manufacture intent data.

The references contain `session_id`, `db_id`, `library_id`, and `design_id`.
These are the same native-coordinate fields used by Kepler MCP. Each bridge
has its own session ID/connection credential even when both bridges share one
interpreter and universe. Obtain the Naja-Scope reference from this bridge;
do not send a Kepler bridge's session ID to it. No design-name map exists.
The variable names `golden_ref` and `edited_ref` have no special API meaning.

## Attach And Select Through MCP

Launch the usual `naja-scope-mcp` server on the same machine and user account.
The following are MCP tool names and their arguments, not a new Python client:

```python
attach_session(connection_file=connection_file)
get_session_binding()

# Explicit per-query selection. Paths are relative to the chosen design's top.
get_drivers(design=golden_ref, path="top.y")
get_drivers(design=edited_ref, path="top.y")
get_loads(design=edited_ref, path="top.a")
get_stats(design=edited_ref)

# Optional default for subsequent calls on this MCP server.
set_session_design(design=golden_ref)
get_drivers(path="top.y")
```

All read-only inspection tools accept `design`. A per-query reference overrides
the selected default for that call only. Prefer explicit per-query references
when multiple agents share an MCP server; its default is not client-private.
Attaching without a design allows discovery but requires selection before a
design query. `attach_session(..., design=golden_ref)` can set the initial default.

Discovery lists at most 200 non-primitive designs and reports
`designs_truncated`. This does not limit lookup: the owner can produce a reference
for any raw SNL design through `scope.design_reference(design)`.

Each query resolves the native IDs afresh and executes under the shared lock
with a scoped inspection root. The owner's global and per-database top selections
are preserved; Naja-Scope's temporary metadata is restored even on failure.
Native cone tracing temporarily changes top selection internally, so the bridge
restores both selections under the shared lock. `trace_cone` requires an existing
global top and a top in the target database: the raw binding cannot restore an
unset top. If either is missing, it rejects tracing before mutation; the owner
can select the tops first. Other inspection tools also work with unset tops.
Results retain their normal fields and add `binding` with the owner process,
session and exact design reference. Queries see the current connectivity after
each completed edit. Naja-Scope inspection is not a formal equivalence proof.

## Lifetime And Trust

- Keep both the owner process and bridge alive. `detach_session()` disconnects
  only the MCP server. `scope.close()` removes only this bridge and its private
  connection file; neither destroys designs.
- A missing design, wrong session, invalid/out-of-range ID, or replaced universe
  is rejected. There is no fallback to a local loaded design.
- Native IDs are coordinates, not generation counters. Close all bridges before
  destroying/reloading designs or databases, then obtain fresh session references.
  Delete-and-recreate may reuse native IDs and cannot always be detected.
- Load, reset, snapshot/export, intent-loading and arbitrary-Python tools are
  blocked while attached, including when `NAJA_SCOPE_ENABLE_PYTHON` is enabled.
- Busy owners reject queries. A timeout does not cancel native work; wait for
  the shared lock before editing, closing or destroying anything.
- The connection file is a credential: keep it private, never commit or log its
  contents. It grants read access to designs in the owner's universe, not just
  the currently selected one. The bridge binds loopback only and authenticates
  requests. It is for trusted same-user clients, not an OS security sandbox.
- The owner's direct Python code can still mutate Naja. MCP read-only enforcement
  does not constrain arbitrary code running in that interpreter.

Without attachment, the existing load/query/reset workflow is unchanged.
