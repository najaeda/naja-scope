# SPDX-License-Identifier: Apache-2.0
"""Cards, find/pagination, hierarchy, stats, status, query_python."""

from naja_scope import api


def test_module_card(uart_session):
    card = api.get_module_card("uart_tx")
    port_names = {p["name"] for p in card["ports"]}
    assert {"clk", "rst_n", "tx_o", "tx_data"} <= port_names
    tx_data = next(p for p in card["ports"] if p["name"] == "tx_data")
    assert tx_data["width"] == 8
    assert tx_data["dir"] == "input"
    assert card["clock_candidates"] == ["clk"]
    assert card["reset_candidates"][0]["name"] == "rst_n"
    assert card["reset_candidates"][0]["active_low_guess"] is True
    assert card["counts"]["sequential_instances"] > 0
    assert "uart.sv" in card.get("src", "")


def test_module_card_suggestions(uart_session):
    from naja_scope.errors import ScopeError
    try:
        api.get_module_card("uart_txx")
        assert False, "expected ScopeError"
    except ScopeError as e:
        assert "uart_tx" in e.suggestions


def test_find_instances(uart_session):
    out = api.find("u_*cnt", kind="instance")
    paths = {m["path"] for m in out["matches"]}
    assert "uart_top.u_tx.u_div_cnt" in paths
    assert "uart_top.u_tx.u_bit_cnt" in paths


def test_find_pagination(uart_session):
    page1 = api.find("*", kind="instance", limit=3)
    assert page1["count"] == 3
    assert page1["has_more"] is True
    page2 = api.find("*", kind="instance", limit=3,
                     cursor=page1["next_cursor"])
    p1 = {m["path"] for m in page1["matches"]}
    p2 = {m["path"] for m in page2["matches"]}
    assert not (p1 & p2)


def test_find_module(uart_session):
    out = api.find("counter*", kind="module")
    assert len(out["matches"]) >= 2  # counter + counter__elab1


def test_hierarchy(uart_session):
    out = api.get_hierarchy(depth=2, limit=10)
    root = out["root"]
    assert root["model"] == "uart_top"
    assert root["children"][0]["model"].startswith("uart_tx")
    assert "children_total" in root


def test_stats(uart_session):
    out = api.get_stats()
    assert out["total_models"] >= 3  # uart_top, uart_tx, counter
    assert out["flat_leaves"] > 0
    assert out["flat_sequential"] > 0
    assert out["models"]


def test_status(uart_session):
    out = api.status()
    assert out["loaded"] is True
    assert out["top"]["model"] == "uart_top"


def test_query_python(uart_session):
    out = api.query_python("get_top().get_name()")
    assert out["result"] == "'uart_top'"


def test_query_python_error_reported(uart_session):
    out = api.query_python("nonexistent_fn()")
    assert "error" in out
