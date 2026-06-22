# SPDX-License-Identifier: Apache-2.0
"""Drivers/loads/cone: the DESIGN.md section-3 workflow."""

from naja_scope import api


def test_drivers_of_registered_output_is_ff(uart_session):
    out = api.get_drivers("uart_top.tx_o")
    leaf = out["leaf_drivers"]
    assert len(leaf) == 1, out
    d = leaf[0]
    assert "dff" in d["model"]
    assert d["is_sequential"] is True
    assert d["pin"] == "Q"
    assert "src" in d and "uart.sv" in d["src"]


def test_loads_of_clock_hits_limit(uart_session):
    # Since najaeda 0.7.0 FFs are word-level primitives (naja_dffrn__w8),
    # so clk has one load per register (5 here), not per bit.
    out = api.get_loads("uart_top.clk", limit=3)
    assert len(out["leaf_loads"]) <= 3
    assert out["truncated"] is True


def test_drivers_of_input_port_is_empty_or_top(uart_session):
    out = api.get_drivers("uart_top.tx_start")
    assert out["leaf_drivers"] == []
    assert len(out["top_drivers"]) >= 1


def test_equipotential_size_reported(uart_session):
    out = api.get_drivers("uart_top.tx_o")
    assert "equipotential_size" in out
    assert out["equipotential_size"] >= 1


# -- trace_cone (SNLLogicalCone-backed; needs najaeda 0.7.6+) -----------------

def test_cone_fanin_reaches_ff(uart_session):
    out = api.trace_cone("uart_top.tx_o", "fanin")
    assert out["direction"] == "fanin"
    assert out["node_count"] >= 2
    assert out["counts_by_kind"].get("flop", 0) >= 1
    fr = out["frontier"]
    assert fr["flop_count"] >= 1
    ff = fr["flops"][0]
    assert ff["path"] == "uart_top.u_tx.tx_o_dff"
    assert "dff" in ff["model"]
    assert "uart.sv" in ff["src"]


def test_cone_traverses_logic_gates_no_blackboxes(uart_session):
    # The 0.7.6 fix gives lowered and/or/not gates combinatorial modeling, so
    # the cone crosses them instead of stopping at a `blackbox` barrier.
    out = api.trace_cone("uart_top.u_tx.state_n", "fanin")
    assert out["frontier"]["blackbox_count"] == 0
    assert out["counts_by_kind"].get("blackbox", 0) == 0
    assert out["counts_by_kind"].get("internal", 0) >= 1


def test_cone_cross_hierarchy_summary(uart_session):
    out = api.trace_cone("uart_top.u_tx.state_n", "fanin")
    ch = out["cross_hierarchy"]
    # Root lives in the u_tx subtree; the summary is anchored there.
    assert ch["root_subtree"] == "uart_top.u_tx"
    assert out["frontier"]["flop_count"] >= 1
    # by_subtree counts sum to the full (deduped) flop frontier.
    assert out["frontier"]["flop_count"] == sum(
        b["count"] for b in ch["by_subtree"].values())
    # outside == every by_subtree bucket that is not the root subtree.
    expect_outside = sum(c["count"] for k, c in ch["by_subtree"].items()
                         if k != ch["root_subtree"])
    assert ch["outside_root_subtree"]["count"] == expect_outside
    assert ch["root_subtree"] not in ch["outside_root_subtree"]["subtrees"]


def test_cone_frontier_bounded(uart_session):
    # Counts stay exact; emitted lists are capped with a truncation marker.
    full = api.trace_cone("uart_top.u_tx.state_n", "fanin")
    capped = api.trace_cone("uart_top.u_tx.state_n", "fanin", max_frontier=1)
    assert capped["frontier"]["flop_count"] == full["frontier"]["flop_count"]
    assert len(capped["frontier"]["flops"]) <= 1
    if full["frontier"]["flop_count"] > 1:
        assert capped["frontier"]["truncated"] is True


def test_cone_fanout_reaches_ff(uart_session):
    out = api.trace_cone("uart_top.tx_start", "fanout")
    assert out["direction"] == "fanout"
    assert out["frontier"]["flop_count"] >= 1


def test_cone_rejects_bad_direction(uart_session):
    import pytest

    from naja_scope.errors import ScopeError
    with pytest.raises(ScopeError):
        api.trace_cone("uart_top.tx_o", "sideways")
