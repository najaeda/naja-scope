# SPDX-License-Identifier: Apache-2.0
"""Regression guard for the bundled examples/ walkthrough.

Loads examples/uart.sv (the same file shipped to users, not the test fixture)
and asserts the exact answers examples/README.md and examples/walkthrough.py
claim. If the tool behavior or the example design drifts, this fails — so the
documented tour can never silently lie.
"""

import os

import pytest

from naja_scope import api
from naja_scope.session import SESSION

EXAMPLE_SV = os.path.join(
    os.path.dirname(__file__), "..", "examples", "uart.sv")


@pytest.fixture(scope="module")
def example_session():
    assert os.path.exists(EXAMPLE_SV), "examples/uart.sv is missing"
    SESSION.reset()
    SESSION.load_systemverilog([EXAMPLE_SV])
    yield SESSION


def test_walkthrough_loads(example_session):
    st = api.status()
    assert st["loaded"] is True
    assert st["top"]["name"] == "uart_top"


def test_walkthrough_hierarchy(example_session):
    root = api.get_hierarchy("uart_top", depth=1)["root"]
    assert root["name"] == "uart_top"
    child_names = [c["name"] for c in root["children"]]
    assert "u_tx" in child_names


def test_walkthrough_drivers_of_tx_o(example_session):
    leaf = api.get_drivers("uart_top.tx_o")["leaf_drivers"][0]
    assert "dff" in leaf["model"]
    assert leaf["is_sequential"] is True
    assert leaf["pin"] == "Q"
    assert "uart.sv" in leaf["src"]


def test_walkthrough_source_behind_flop(example_session):
    leaf = api.get_drivers("uart_top.tx_o")["leaf_drivers"][0]
    src = api.get_source(leaf["path"])
    assert "uart.sv" in src["src"]
    assert "tx_o" in (src.get("text") or "")


def test_walkthrough_fanin_cone_fully_combinational(example_session):
    cone = api.trace_cone("uart_top.u_tx.state_n", "fanin")
    assert cone["node_count"] >= 2
    assert cone["frontier"]["blackbox_count"] == 0
    assert cone["frontier"]["flop_count"] >= 1
