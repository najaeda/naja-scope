#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Load one benchmark design and expose its warm naja-scope MCP session."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(HERE))

from run_comparison import config_fingerprint, git_metadata, load_config  # noqa: E402
from naja_scope import api, server  # noqa: E402
from naja_scope.session import SESSION  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--ready-file", type=Path, required=True)
    args = parser.parse_args()

    source_root = args.source_root.resolve()
    config = load_config(args.config.resolve(), source_root)
    source = git_metadata(source_root)
    for key, value in config.get("environment", {}).items():
        os.environ[str(key)] = str(value)

    load = config["load"]
    started = time.monotonic()
    SESSION.reset()
    api.load_systemverilog(
        flist=load["flist"], top=load.get("top"),
        intent=bool(load.get("intent", True)))
    status = api.status()
    load_seconds = round(time.monotonic() - started, 3)

    server.mcp.settings.host = args.host
    server.mcp.settings.port = args.port
    url = f"http://{args.host}:{args.port}{server.mcp.settings.streamable_http_path}"
    ready = {
        "url": url,
        "fingerprint": config_fingerprint(config, source),
        "load_seconds": load_seconds,
        "status": status,
    }
    args.ready_file.write_text(json.dumps(ready, indent=2), encoding="utf-8")
    server.mcp.run(transport="streamable-http")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
