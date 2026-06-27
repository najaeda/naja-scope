# SPDX-License-Identifier: Apache-2.0
"""Snapshot save + reload (naja-if; SV-snapshot reload fixed in najaeda 0.7.4).
Named test_zz_* to run last: it resets the universe, which invalidates the
session-scoped fixture other files share."""

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

    # The load_spec (elaboration inputs) survives the snapshot so the warm-only
    # intent layer can be re-loaded after a cold reload (productization).
    from naja_scope.session import SESSION
    assert any("uart.sv" in f for f in (SESSION.load_spec.get("files") or []))
    assert api.status()["intent_loadable"] is True


def test_snapshot_reload_with_intent(uart_session, tmp_path):
    """End-to-end: a cold snapshot reload brings the intent layer up by
    re-elaborating WITH the AST link from the persisted flist/files (warm-only;
    the relink-without-re-elaboration tier is deferred), and answers get_intent.
    No pyslang — the facts come from naja.intent_* over the in-engine link."""
    import pytest
    snap = str(tmp_path / "snap3")
    os.makedirs(snap, exist_ok=True)
    api.save_snapshot(snap)
    api.reset_universe()

    loaded = api.load_snapshot(snap, intent=True)
    assert loaded["top"]["model"] == "uart_top"
    if not loaded.get("intent_loaded"):
        pytest.skip("naja build without the SNL↔slang link (keep_ast_link)")
    # uart_tx carries a DIV_W parameter + IDLE/START/DATA/STOP localparams.
    params = api.get_intent("uart_top.u_tx", want="parameters")
    names = {p["name"] for p in params["parameters"]}
    assert "DIV_W" in names


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
        "get_intent", "load_intent",
    }
    assert expected <= names, expected - names
