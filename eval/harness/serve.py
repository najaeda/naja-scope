# SPDX-License-Identifier: Apache-2.0
"""Warm naja-scope server for the eval (arm A).

Loads a design ONCE, then serves the registered naja-scope MCP tools so every
eval question reuses the warm session — re-spawning a stdio server per
`claude -p` would re-pay the load each time.

najaeda 0.7.4 fixes SV-snapshot reload, so the first elaboration is saved to a
naja-if snapshot cache (designs.snapshot_dir) and reloaded on every later
warm-server start. (Post-0.7.7 the eager naming pass is gone, so cold
elaboration is itself cheap — ~12s cva6-small / ~29s cva6-full on 0.7.8 — making
the cache a minor convenience.) Pass --refresh-cache to force re-elaboration.

Transports:
  --transport sse     long-lived daemon; point Claude Code's MCP client at the
                      URL (http://HOST:PORT/sse). Loaded once, shared by all
                      arm-A questions.
  --transport stdio   one process per session (fine for the UART fixture, which
                      loads in <1s).

Readiness: with --ready-file, the JSON summary of the loaded top is written
*after* elaboration completes (and, for sse, the bound URL), so run_eval.py can
block until the design is actually queryable.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

# Route naja's C++ stdout logging to stderr before anything loads, exactly as
# server.main() does, so it never corrupts an stdio JSON-RPC stream.
_real_stdout = os.dup(1)
os.dup2(2, 1)

# Make the package importable when run as a plain script.
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import designs as design_registry  # noqa: E402
from naja_scope import api, server  # noqa: E402


def load_design(design_key: str, refresh_cache: bool = False,
                intent: bool = False) -> dict:
    spec = design_registry.get(design_key)
    for k, v in spec["env"].items():
        os.environ.setdefault(k, v)
    cache = design_registry.snapshot_dir(design_key)
    cached = os.path.isfile(os.path.join(cache, "snl.mf"))
    t0 = time.time()
    # The intent layer needs the live slang AST (keep_ast_link), which a naja-if
    # snapshot cannot carry — so with intent we always elaborate from source in a
    # single pass (cheap post-0.7.7: ~12s cva6-small / ~29s cva6-full) and skip
    # the snapshot round-trip. Without intent, the cache short-circuits the load.
    if cached and not refresh_cache and not intent:
        res = api.load_snapshot(cache)
        res["source"] = "snapshot"
    else:
        load = spec["load"]
        api.load_systemverilog(
            files=load.get("files"), flist=load.get("flist"),
            top=spec.get("top"), intent=intent)
        os.makedirs(cache, exist_ok=True)
        api.save_snapshot(cache)
        res = api.status()
        res["source"] = "elaborated"
    res["load_seconds"] = round(time.time() - t0, 2)
    res["design"] = design_key
    res["label"] = spec["label"]
    res["intent_loaded"] = api.SESSION.intent_available
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description="Warm naja-scope server for eval")
    ap.add_argument("--design", required=True, choices=list(design_registry.DESIGNS))
    ap.add_argument("--transport", default="sse", choices=["sse", "stdio"])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--ready-file", default=None)
    ap.add_argument("--refresh-cache", action="store_true",
                    help="ignore any cached snapshot and re-elaborate from source")
    ap.add_argument("--intent", action="store_true",
                    help="retain the in-engine SNL↔slang link (keep_ast_link) so "
                         "get_intent is available (phase-2 gate, arm A)")
    args = ap.parse_args()

    summary = load_design(args.design, refresh_cache=args.refresh_cache,
                          intent=args.intent)
    if args.intent:
        print(f"[serve] intent layer loaded: {summary.get('intent_loaded')}",
              file=sys.stderr)
    if args.transport == "sse":
        server.mcp.settings.host = args.host
        server.mcp.settings.port = args.port
        summary["url"] = f"http://{args.host}:{args.port}{server.mcp.settings.sse_path}"

    if args.ready_file:
        with open(args.ready_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

    # Hand the MCP transport a private duplicate of the real stdout (stdio only).
    import io
    sys.stdout = io.TextIOWrapper(os.fdopen(_real_stdout, "wb"),
                                  encoding="utf-8", line_buffering=True)
    print(f"[serve] {args.design} loaded in {summary['load_seconds']}s; "
          f"transport={args.transport}", file=sys.stderr)
    server.mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
