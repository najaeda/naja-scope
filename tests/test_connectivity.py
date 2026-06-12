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


def test_cone_fanin_stops_at_flops(uart_session):
    out = api.trace_cone("uart_top.tx_o", "fanin", stop="flops")
    assert out["node_count"] >= 1
    reasons = {f["reason"] for f in out["frontier"]}
    assert reasons.issubset({"flop", "port", "max_depth"})
    assert out["counts_by_model"]
    assert out["truncated"] is False


def test_cone_max_nodes_truncates(uart_session):
    out = api.trace_cone("uart_top.u_tx.state_n", "fanin", stop="none",
                         max_nodes=2)
    assert out["node_count"] <= 2
    assert out["truncated"] is True


def test_cone_fanout(uart_session):
    out = api.trace_cone("uart_top.tx_start", "fanout", stop="flops")
    assert out["node_count"] >= 1
