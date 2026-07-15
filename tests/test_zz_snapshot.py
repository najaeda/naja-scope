# SPDX-License-Identifier: Apache-2.0
"""Snapshot save + reload (naja-if).
Named test_zz_* to run last: it resets the universe, which invalidates the
session-scoped fixture other files share."""

import os

from naja_scope import api

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
UART_SV = os.path.join(FIXTURES, "uart.sv")


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


def test_status_reports_intent_loadable_contract(uart_session):
    """status() is how an agent decides whether get_intent can be brought up:
    `intent_loadable` is True iff the elaboration inputs are known (warm reload
    possible), independent of whether the link is live right now. Build-agnostic
    — it reads metadata, not the AST link, so it runs on PyPI builds too."""
    from naja_scope.session import SESSION
    # `intent_loaded` reflects the live link (in-process, order-dependent here);
    # the order-independent contract under test is `intent_loadable`: uart was
    # loaded from a real file, so the inputs are captured and a warm reload is
    # possible.
    st = api.status()
    assert isinstance(st["intent_loaded"], bool)
    assert st["intent_loadable"] is True
    # A cold snapshot that carries no load_spec (old/foreign snapshot) reports
    # not-loadable, so the agent knows load_intent needs an explicit flist/files.
    saved = SESSION.load_spec
    SESSION.load_spec = {}
    try:
        assert api.status()["intent_loadable"] is False
    finally:
        SESSION.load_spec = saved


def test_load_snapshot_intent_without_load_spec(uart_session, tmp_path,
                                                monkeypatch):
    """A cold snapshot that does not carry the elaboration inputs (an old or
    externally produced snapshot) cannot bring intent up by re-elaboration:
    explicit intent=True must RAISE (the agent asked and we can't comply), while
    the env opt-in must DEGRADE — never failing the load. Build-agnostic: a cold
    snapshot never has a live link regardless of the naja build."""
    import json
    import pytest
    from naja_scope.errors import ScopeError
    from naja_scope.session import SESSION

    snap = str(tmp_path / "snap_nospec")
    os.makedirs(snap, exist_ok=True)
    api.save_snapshot(snap)
    # Strip load_spec from the sidecar to simulate a snapshot without inputs.
    meta_path = os.path.join(snap, "naja_scope_session.json")
    with open(meta_path) as f:
        meta = json.load(f)
    meta["load_spec"] = {}
    with open(meta_path, "w") as f:
        json.dump(meta, f)

    # explicit intent=True -> ScopeError (no flist/files to re-elaborate).
    api.reset_universe()
    monkeypatch.delenv("NAJA_SCOPE_INTENT", raising=False)
    with pytest.raises(ScopeError):
        api.load_snapshot(snap, intent=True)

    # env opt-in -> graceful degradation, load still succeeds.
    api.reset_universe()
    monkeypatch.setenv("NAJA_SCOPE_INTENT", "1")
    out = api.load_snapshot(snap)
    assert out["top"]["model"] == "uart_top"
    assert out["intent_loaded"] is False
    assert "intent_note" in out

    # Restore the canonical uart universe for any later test files.
    monkeypatch.delenv("NAJA_SCOPE_INTENT", raising=False)
    SESSION.reset()
    SESSION.load_systemverilog([UART_SV])


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
        "get_module_card", "get_stats",
        "get_intent", "load_intent",
    }
    assert expected <= names, expected - names
    # query_python is opt-in (NAJA_SCOPE_ENABLE_PYTHON) and registered at import
    # time, so its presence here just tracks the ambient env.
    assert ("query_python" in names) == bool(
        os.environ.get("NAJA_SCOPE_ENABLE_PYTHON"))
