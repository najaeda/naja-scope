# SPDX-License-Identifier: Apache-2.0
"""Snapshot save + (currently upstream-broken) reload. Named test_zz_* to run
last: it resets the universe, which invalidates the session-scoped fixture
other files share."""

import os

from naja_scope import api


def test_save_snapshot_writes_netlist_and_meta(uart_session, tmp_path):
    snap = str(tmp_path / "snap")
    os.makedirs(snap, exist_ok=True)
    saved = api.save_snapshot(snap)
    assert saved["path"] == snap
    files = set(os.listdir(snap))
    assert "snl.mf" in files
    assert "naja_scope_session.json" in files
    # The source-index sidecar is gone (source is read on demand).
    assert "naja_scope_source_index.json" not in files


def test_snapshot_reload_roundtrip(uart_session, tmp_path):
    snap = str(tmp_path / "snap2")
    os.makedirs(snap, exist_ok=True)
    saved = api.save_snapshot(snap)

    api.reset_universe()
    assert api.status()["loaded"] is False

    loaded = api.load_snapshot(snap)
    assert loaded["top"]["model"] == "uart_top"

    # Named paths, anonymous `#id` paths, and source ranges survive the
    # round-trip (the `#id` segment is the FF's snapshot-stable getID()).
    out = api.resolve("uart_top.u_tx.u_div_cnt")
    assert out["matches"][0]["path"] == "uart_top.u_tx.u_div_cnt"
    drivers = api.get_drivers("uart_top.tx_o")
    leaf_path = drivers["leaf_drivers"][0]["path"]
    src = api.get_source(leaf_path)
    assert "always_ff" in src.get("text", "")


def test_server_tools_registered():
    from naja_scope import server

    async def _list():
        return await server.mcp.list_tools()

    import asyncio
    tools = asyncio.run(_list())
    names = {t.name for t in tools}
    expected = {
        "status", "load_systemverilog", "load_verilog", "load_liberty",
        "load_primitives", "save_snapshot", "load_snapshot",
        "reset_universe", "resolve", "find", "get_hierarchy",
        "get_drivers", "get_loads", "trace_cone", "get_source",
        "get_module_card", "get_stats", "query_python",
    }
    assert expected <= names, expected - names
