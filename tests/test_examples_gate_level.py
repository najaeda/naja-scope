# SPDX-License-Identifier: Apache-2.0
"""Regression guard for the bundled gate-level example.

Loads examples/stdcells.lib + examples/counter2.v (the same files shipped to
users and used by examples/gate_level.py) and asserts the answers the example
claims. This pins naja-scope's gate-level path: Liberty cell library +
structural Verilog netlist, navigated for hierarchy, cell counts, drivers, and
logic cones.
"""

import os

import pytest

from naja_scope import api
from naja_scope.session import SESSION

HERE = os.path.dirname(__file__)
LIB = os.path.join(HERE, "..", "examples", "stdcells.lib")
NETLIST = os.path.join(HERE, "..", "examples", "counter2.v")


@pytest.fixture(scope="module")
def gate_session():
    assert os.path.exists(LIB), "examples/stdcells.lib is missing"
    assert os.path.exists(NETLIST), "examples/counter2.v is missing"
    SESSION.reset()
    api.load_liberty([LIB])
    api.load_verilog([NETLIST])
    yield SESSION
    # Restore a clean universe for the rest of the suite.
    SESSION.reset()


def test_gate_level_loads(gate_session):
    st = api.status()
    assert st["loaded"] is True
    assert st["top"]["name"] == "counter2"


def test_gate_level_hierarchy_is_cells(gate_session):
    root = api.get_hierarchy("counter2", depth=1)["root"]
    models = sorted(c["model"] for c in root["children"])
    # 2 flops + an inverter + an xor, all standard cells from the library.
    assert models == ["DFF", "DFF", "INV", "XOR2"]
    assert all(c["leaf"] for c in root["children"])


def test_gate_level_module_card_counts(gate_session):
    card = api.get_module_card("counter2")
    assert card["counts"]["by_model"] == {"DFF": 2, "INV": 1, "XOR2": 1}
    assert card["counts"]["instances"] == 4
    assert [p["name"] for p in card["ports"]] == ["clk", "q0", "q1"]


def test_gate_level_resolve_cell(gate_session):
    m = api.resolve("counter2.u_ff0")["matches"][0]
    assert m["kind"] == "instance"
    assert m["model"] == "DFF"


def test_gate_level_drivers_of_output(gate_session):
    leaf = api.get_drivers("counter2.q1")["leaf_drivers"][0]
    assert leaf["path"] == "counter2.u_ff1"
    assert leaf["model"] == "DFF"
    assert leaf["pin"] == "Q"


def test_gate_level_fanin_cone_stops_at_flops(gate_session):
    # q1_next = q1 ^ q0, so the fan-in of the q1 flop's D reaches both flops.
    # They are opaque library cells, so the cone stops at them as its cell
    # (black-box) frontier.
    cone = api.trace_cone("counter2.u_ff1.D", "fanin")
    stopped = {b["path"] for b in cone["frontier"]["blackboxes"]}
    assert stopped == {"counter2.u_ff0", "counter2.u_ff1"}
