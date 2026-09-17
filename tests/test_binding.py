# SPDX-License-Identifier: Apache-2.0
"""Real in-memory designs and MCP transport, without a Kepler/22b dependency."""

import asyncio
import json
import os
from pathlib import Path
import socket
import struct
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from najaeda import naja
from pydantic import ValidationError

from naja_scope import api, server
from naja_scope.binding import (MAX_REQUEST, READ_ONLY_TOOLS,
                                SessionBinding, SessionBridge, _Client, _receive)
from naja_scope.design_reference import DesignReference
from naja_scope.errors import ScopeError
from naja_scope.session import SESSION


def make_design(universe, driver="a"):
    database = naja.NLDB.create(universe)
    library = naja.NLLibrary.create(database, "designs")
    design = naja.SNLDesign.create(library, "top")
    for name in ("a", "b"):
        net = naja.SNLScalarNet.create(design, name)
        naja.SNLScalarTerm.create(design, naja.SNLTerm.Direction.Input, name).setNet(net)
    naja.SNLScalarTerm.create(design, naja.SNLTerm.Direction.Output, "y").setNet(
        design.getNet(driver))
    return design


@pytest.fixture
def live():
    SESSION.reset()
    universe = naja.NLUniverse.create()
    golden, edited = make_design(universe), make_design(universe, "b")
    universe.setTopDesign(edited)
    universe.setTopDesign(golden)
    lock = threading.RLock()
    bridge = SessionBridge(lock=lock).start()
    binding = SessionBinding()
    references = [bridge.design_reference(design) for design in (golden, edited)]
    yield SimpleNamespace(universe=universe, golden=golden, edited=edited,
                          bridge=bridge, binding=binding, refs=references, lock=lock)
    binding.detach()
    bridge.close()
    SESSION.reset()


def query(live, tool="get_drivers", *, design=None, **arguments):
    return live.binding.invoke(tool, arguments, lambda: pytest.fail("No local fallback"), design)


def test_switch_same_named_designs_by_native_database_id(live):
    first, second = live.refs
    assert first["db_id"] != second["db_id"]
    assert first["library_id"] == second["library_id"]
    assert first["design_id"] == second["design_id"]
    info = live.binding.attach(live.bridge.connection_file, first)
    assert info["design_addressing"] == "native-id-v1"
    assert [d["name"] for d in info["designs"]] == ["top", "top"]
    assert not hasattr(live.bridge, "_designs")
    for reference, expected in ((first, "top.a"), (second, "top.b"), (first, "top.a")):
        live.binding.select(reference)
        result = query(live, path="top.y")
        assert result["top_drivers"] == [{"port": expected, "dir": "input"}]
        assert result["binding"]["design"] == reference
        assert live.universe.getTopDesign() == live.golden
        assert live.universe.getTopDB() == live.golden.getDB()
        assert api.SESSION is SESSION


def test_query_override_does_not_change_default_and_sees_cumulative_edits(live):
    live.binding.attach(live.bridge.connection_file, live.refs[0])
    result = query(live, design=live.refs[1], path="top.y")
    assert result["top_drivers"][0]["port"] == "top.b"
    assert live.binding.inspect()["selected_design"] == live.refs[0]
    with live.lock:
        live.edited.getScalarTerm("y").setNet(live.edited.getNet("a"))
    assert query(live, design=live.refs[1], path="top.y")["top_drivers"][0]["port"] == "top.a"
    with live.lock:
        live.edited.getScalarTerm("y").setNet(live.edited.getNet("b"))
    assert query(live, design=live.refs[1], path="top.y")["top_drivers"][0]["port"] == "top.b"
    assert query(live, path="top.y")["binding"]["design"] == live.refs[0]


@pytest.mark.parametrize("tool,arguments", [
    ("status", {}), ("resolve", {"path": "top.y"}),
    ("find", {"pattern": "*"}), ("get_hierarchy", {}),
    ("get_drivers", {"path": "top.y"}), ("get_loads", {"path": "top.b"}),
    ("trace_cone", {"path": "top.y", "direction": "fanin"}),
    ("get_stats", {}), ("get_module_card", {"module": "top"}),
    ("get_intent", {"ref": "top.y"}),
])
def test_all_typed_queries_match_direct_api_on_selected_design(live, tool, arguments):
    live.binding.attach(live.bridge.connection_file)
    with live.lock:
        naja.SNLScalarTerm.create(live.edited, naja.SNLTerm.Direction.Input, "only_edited")
        live.universe.setTopDesign(live.edited)
        expected = getattr(api, tool)(**arguments)
        live.universe.setTopDesign(live.golden)
    result = query(live, tool, design=live.refs[1], **arguments)
    result.pop("binding")
    assert result == expected
    assert live.universe.getTopDesign() == live.golden


def test_returned_selection_cannot_mutate_retained_default(live):
    result = live.binding.attach(live.bridge.connection_file, live.refs[0])
    result["selected_design"]["db_id"] = live.refs[1]["db_id"]
    result = live.binding.select(live.refs[0])
    result["selected_design"]["db_id"] = live.refs[1]["db_id"]
    result = live.binding.inspect()
    result["selected_design"]["db_id"] = live.refs[1]["db_id"]
    assert query(live, path="top.y")["binding"]["design"] == live.refs[0]


def test_discover_then_require_explicit_selection(live):
    info = live.binding.attach(live.bridge.connection_file)
    assert info["selected_design"] is None
    with pytest.raises(ScopeError, match="Supply a native"):
        query(live, path="top.y")
    assert query(live, design=live.refs[1], path="top.y")["top_drivers"][0]["port"] == "top.b"


def test_queries_preserve_all_native_top_selections_including_unset(live):
    live.binding.attach(live.bridge.connection_file)
    with live.lock:
        unselected = make_design(live.universe)
    reference = live.bridge.design_reference(unselected)
    databases = list(live.universe.getUserDBs())
    before = [db.getTopDesign() for db in databases]
    assert unselected.getDB().getTopDesign() is None
    for tool, arguments in (("status", {}), ("get_drivers", {"path": "top.y"})):
        query(live, tool, design=reference, **arguments)
        assert [db.getTopDesign() for db in databases] == before
        assert live.universe.getTopDesign() == live.golden
    with pytest.raises(ScopeError, match="target-database tops"):
        query(live, "trace_cone", design=reference, path="top.y", direction="fanin")
    assert [db.getTopDesign() for db in databases] == before


def test_cone_restores_target_database_top_even_when_querying_another_model(live):
    with live.lock:
        extra = naja.SNLDesign.create(live.edited.getLibrary(), "extra")
        n = naja.SNLScalarNet.create(extra, "i")
        naja.SNLScalarTerm.create(extra, naja.SNLTerm.Direction.Input, "i").setNet(n)
        naja.SNLScalarTerm.create(extra, naja.SNLTerm.Direction.Output, "o").setNet(n)
    reference = live.bridge.design_reference(extra)
    live.binding.attach(live.bridge.connection_file)
    query(live, "trace_cone", design=reference, path="extra.o", direction="fanin")
    assert live.universe.getTopDesign() == live.golden
    assert live.edited.getDB().getTopDesign() == live.edited


def test_bridge_does_not_require_an_owner_top():
    SESSION.reset()
    universe = naja.NLUniverse.create()
    design = make_design(universe)
    binding = SessionBinding()
    try:
        with SessionBridge() as bridge:
            binding.attach(bridge.connection_file)
            result = binding.invoke("get_drivers", {"path": "top.y"},
                                    lambda: pytest.fail("No local fallback"), bridge.design_reference(design))
            assert result["top_drivers"][0]["port"] == "top.a"
            assert universe.getTopDesign() is None
            assert design.getDB().getTopDesign() is None
            with pytest.raises(ScopeError, match="global and target-database tops"):
                binding.invoke("trace_cone", {"path": "top.y", "direction": "fanin"},
                               lambda: pytest.fail("No local fallback"), bridge.design_reference(design))
            binding.detach()
    finally:
        SESSION.reset()


def test_new_designs_are_visible_without_registration_and_renames_keep_ids(live):
    live.binding.attach(live.bridge.connection_file)
    with live.lock:
        another = make_design(live.universe)
    reference = live.bridge.design_reference(another)
    assert reference in [d["reference"] for d in live.binding.inspect()["designs"]]
    with live.lock:
        another.setName("renamed")
    assert live.bridge.design_reference(another) == reference
    result = query(live, design=reference, path="renamed.y")
    assert result["top_drivers"][0]["port"] == "renamed.a"


def test_library_and_design_ids_select_exact_model_even_with_duplicate_names(live):
    with live.lock:
        library = naja.NLLibrary.create(live.golden.getDB(), "another_library")
        other = naja.SNLDesign.create(library, "top")
        naja.SNLScalarTerm.create(other, naja.SNLTerm.Direction.Input, "only_here")
        third = naja.SNLDesign.create(library, "third")
    second_ref, third_ref = [live.bridge.design_reference(d) for d in (other, third)]
    assert second_ref["db_id"] == live.refs[0]["db_id"]
    assert second_ref["library_id"] != live.refs[0]["library_id"]
    assert second_ref["design_id"] == live.refs[0]["design_id"]
    assert third_ref["library_id"] == second_ref["library_id"]
    assert third_ref["design_id"] != second_ref["design_id"]
    live.binding.attach(live.bridge.connection_file)
    for reference, model in ((live.refs[0], live.golden), (second_ref, other), (third_ref, third)):
        with live.lock:
            live.universe.setTopDesign(model)
            expected = api.get_module_card(model.getName())
            live.universe.setTopDesign(live.golden)
        result = query(live, "get_module_card", design=reference, module=model.getName())
        result.pop("binding")
        assert result == expected
    with pytest.raises(ScopeError, match="Ambiguous"):
        query(live, "get_module_card", design=third_ref, module="top")
    assert live.universe.getTopDesign() == live.golden


@pytest.mark.parametrize("field,value", [
    ("db_id", -1), ("db_id", 256), ("library_id", 65536), ("design_id", 4294967296),
    ("db_id", True), ("db_id", "1"), ("library_id", 0.0), ("session_id", ""),
    ("session_id", 123), ("name", "golden"),
])
def test_reference_rejects_coercion_truncation_and_aliases(live, field, value):
    bad = dict(live.refs[0], **{field: value})
    with pytest.raises(ValidationError):
        DesignReference.model_validate(bad)
    live.binding.attach(live.bridge.connection_file)
    with pytest.raises(ScopeError):
        query(live, design=bad, path="top.y")
    # The owner validates too, not just the public MCP/client schema.
    client = _Client(live.bridge.connection_file, 2)
    with pytest.raises(ScopeError):
        client.call("query", tool="get_drivers", design=bad, arguments={"path": "top.y"})


def test_other_session_missing_and_deleted_designs_never_fall_back(live):
    live.binding.attach(live.bridge.connection_file, live.refs[0])
    for bad in (dict(live.refs[1], session_id="another-session"),
                dict(live.refs[1], design_id=1000)):
        with pytest.raises(ScopeError):
            live.binding.select(bad)
        assert live.binding.inspect()["selected_design"] == live.refs[0]
    with live.lock:
        live.edited.destroy()
    with pytest.raises(ScopeError, match="does not exist"):
        query(live, design=live.refs[1], path="top.y")


def test_replaced_universe_is_rejected(live):
    live.binding.attach(live.bridge.connection_file, live.refs[0])
    with live.lock:
        live.universe.destroy()
        replacement = naja.NLUniverse.create()
        replacement.setTopDesign(make_design(replacement))
    with pytest.raises(ScopeError, match="no longer valid"):
        query(live, path="top.y")


@pytest.mark.parametrize("tool", ["reset_universe", "load_verilog", "load_systemverilog",
                                 "load_liberty", "load_primitives", "load_snapshot",
                                 "save_snapshot", "load_intent", "query_python"])
def test_attached_mode_blocks_mutations_on_client_and_owner(live, tool):
    live.binding.attach(live.bridge.connection_file, live.refs[0])
    with pytest.raises(ScopeError, match="read-only"):
        query(live, tool)
    with pytest.raises(ScopeError, match="read-only"):
        _Client(live.bridge.connection_file, 2).call(
            "query", tool=tool, design=live.refs[0], arguments={})
    assert live.universe.getTopDesign() == live.golden


def test_owner_lock_blocks_inspection_and_exceptions_restore_top(live, monkeypatch):
    live.binding.attach(live.bridge.connection_file, live.refs[1])
    with live.lock:
        with pytest.raises(ScopeError, match="busy"):
            query(live, path="top.y")
    with pytest.raises(ScopeError):
        query(live, path="top.missing")
    assert live.universe.getTopDesign() == live.golden
    assert api.SESSION is SESSION
    def broken(**kwargs):
        raise RuntimeError("native query error")
    monkeypatch.setattr(api, "get_drivers", broken)
    with pytest.raises(ScopeError, match="native query error"):
        query(live, path="top.y")
    assert live.universe.getTopDesign() == live.golden
    assert api.SESSION is SESSION


def test_timeout_keeps_owner_locked_until_query_finishes(live, monkeypatch):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = api.get_drivers
    def slow(**kwargs):
        entered.set()
        try:
            assert release.wait(3)
            return original(**kwargs)
        finally:
            finished.set()
    monkeypatch.setattr(api, "get_drivers", slow)
    live.binding.attach(live.bridge.connection_file, live.refs[1])
    live.binding._client.timeout = 0.1
    try:
        with pytest.raises(ScopeError, match="timed out"):
            query(live, path="top.y")
        assert entered.is_set()
        acquired = live.lock.acquire(blocking=False)
        if acquired:
            live.lock.release()
        assert not acquired
    finally:
        release.set()
        assert finished.wait(3)
        with live.lock:
            pass
    assert live.universe.getTopDesign() == live.golden


def test_close_detach_and_local_mode_preserve_owner_designs(live):
    live.binding.attach(live.bridge.connection_file, live.refs[1])
    assert live.binding.detach()["caller_designs_preserved"]
    assert live.binding.invoke("status", {}, api.status)["top"]["name"] == "top"
    with pytest.raises(ScopeError, match="requires an attached"):
        query(live, design=live.refs[0], path="top.y")
    live.bridge.close()
    assert not live.bridge.connection_file.exists()
    assert naja.NLUniverse.get() is live.universe
    assert live.golden.getName() == live.edited.getName() == "top"
    with pytest.raises(ScopeError):
        live.bridge.start()


def test_authentication_protocol_and_remote_host_rejection(live, tmp_path):
    client = _Client(live.bridge.connection_file, 2)
    client.connection["token"] = "0" * 64
    with pytest.raises(ScopeError, match="authentication"):
        client.call("inspect")
    connection = json.loads(live.bridge.connection_file.read_text())
    for changes in ({"protocol": "unknown"}, {"host": "example.com"}, {"port": True}):
        path = tmp_path / "invalid.json"
        path.write_text(json.dumps(dict(connection, **changes)))
        path.chmod(0o600)
        with pytest.raises(ScopeError):
            _Client(path, 2)
    if os.name == "posix":
        live.bridge.connection_file.chmod(0o644)
        with pytest.raises(ScopeError, match="private"):
            _Client(live.bridge.connection_file, 2)


def test_oversized_request_rejected(live):
    connection = json.loads(live.bridge.connection_file.read_text())
    with socket.create_connection(("127.0.0.1", connection["port"]), timeout=2) as sock:
        sock.sendall(struct.pack("!I", MAX_REQUEST + 1))
        assert "error" in _receive(sock, 4096, time.monotonic() + 2)


def test_wrong_response_design_rejected(live, monkeypatch):
    live.binding.attach(live.bridge.connection_file, live.refs[0])
    monkeypatch.setattr(live.binding._client, "call", lambda *a, **k: {
        "session_id": live.bridge.session_id, "pid": os.getpid(),
        "design": live.refs[1], "result": {"loaded": True}})
    with pytest.raises(ScopeError, match="does not match"):
        query(live, path="top.y")


def test_dead_owner_does_not_fall_back_to_local(live):
    live.binding.attach(live.bridge.connection_file, live.refs[0])
    live.bridge.close()
    with pytest.raises(ScopeError, match="unavailable"):
        query(live, path="top.y")
    assert live.binding._client is not None


def test_existing_warm_source_and_intent_are_reused(uart_session):
    source = Path(__file__).parent / "fixtures/uart.sv"
    SESSION.reset()
    SESSION.load_systemverilog([str(source)], keep_ast_link=True)
    expected_source = api.get_source("uart_top.u_tx.u_div_cnt")
    expected_intent = api.get_intent("uart_top.u_tx", want="parameters")
    universe = naja.NLUniverse.get()
    top = universe.getTopDesign()
    binding = SessionBinding()
    with SessionBridge(source_files=[source]) as bridge:
        reference = bridge.design_reference(top)
        binding.attach(bridge.connection_file, reference)
        for tool, args, expected in (
            ("get_source", {"path": "uart_top.u_tx.u_div_cnt"}, expected_source),
            ("get_intent", {"ref": "uart_top.u_tx", "want": "parameters"}, expected_intent),
        ):
            result = binding.invoke(tool, args, lambda: pytest.fail("No local fallback"))
            result.pop("binding")
            assert result == expected
        binding.detach()
    assert naja.NLUniverse.get() is universe and universe.getTopDesign() == top


def test_discovery_is_bounded_but_does_not_limit_native_resolution(live):
    with live.lock:
        library = live.edited.getLibrary()
        for index in range(205):
            last = naja.SNLDesign.create(library, f"extra_{index}")
    info = live.binding.attach(live.bridge.connection_file)
    assert len(info["designs"]) == 200 and info["designs_truncated"]
    reference = live.bridge.design_reference(last)
    assert query(live, "status", design=reference)["top"]["name"] == "extra_204"


def test_mcp_schemas_offer_typed_references_on_all_queries():
    tools = {tool.name: tool for tool in asyncio.run(server.mcp.list_tools())}
    for name in READ_ONLY_TOOLS | {"attach_session", "set_session_design"}:
        schema = tools[name].inputSchema
        assert "design" in schema["properties"]
        fields = schema["$defs"]["DesignReference"]
        assert set(fields["required"]) == {"session_id", "db_id", "library_id", "design_id"}
        assert fields["additionalProperties"] is False


def test_real_stdio_mcp_inspects_both_designs_in_owner_process(live):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def run():
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"),
                   NAJA_SCOPE_ENABLE_PYTHON="1")
        params = StdioServerParameters(command=sys.executable, args=["-m", "naja_scope.server"], env=env)
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as client:
                await client.initialize()
                async def call(name, **arguments):
                    response = await client.call_tool(name, arguments)
                    assert not response.isError, response
                    return response.structuredContent or json.loads(response.content[0].text)
                attached = await call("attach_session", connection_file=str(live.bridge.connection_file))
                assert attached["pid"] == os.getpid()
                for reference, expected in ((live.refs[0], "top.a"), (live.refs[1], "top.b")):
                    result = await call("get_drivers", design=reference, path="top.y")
                    assert result["top_drivers"][0]["port"] == expected
                    assert result["binding"]["design"] == reference
                with live.lock:
                    live.edited.getScalarTerm("y").setNet(live.edited.getNet("a"))
                await call("set_session_design", design=live.refs[1])
                result = await call("get_drivers", path="top.y")
                assert result["top_drivers"][0]["port"] == "top.a"
                assert "error" in await call("query_python", code="1+1")
                assert "error" in await call("reset_universe")
                invalid = await client.call_tool("get_drivers", {"path": "top.y", "design": dict(live.refs[0], db_id=256)})
                assert invalid.isError
                await call("detach_session")
                assert (await call("status"))["loaded"] is False
    asyncio.run(run())
    assert live.universe.getTopDesign() == live.golden
