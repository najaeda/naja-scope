# SPDX-License-Identifier: Apache-2.0
"""Four-state constant drivers from najaeda's typed SNL nets."""

import os

import pytest

from naja_scope import __version__, api
from naja_scope.session import SESSION

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "net_types.sv")


@pytest.fixture
def net_types_session():
    SESSION.reset()
    SESSION.load_systemverilog([FIXTURE])
    yield SESSION


def test_runtime_version_matches_release():
    assert __version__ == "0.1.9"


@pytest.mark.parametrize(
    ("signal", "value"),
    [
        ("unknown_o", "X"),
        ("high_z_o", "Z"),
        ("zero_o", "0"),
        ("one_o", "1"),
    ],
)
def test_scalar_literal_driver_value(net_types_session, signal, value):
    drivers = api.get_drivers(f"net_types.{signal}")["leaf_drivers"]
    assert len(drivers) == 1
    assert drivers[0]["model"] == "assign"
    assert drivers[0]["constant"] == value


def test_mixed_four_state_bus_driver_values(net_types_session):
    drivers = api.get_drivers("net_types.mixed_o")["leaf_drivers"]
    by_bit = {driver["bit"]: driver["constant"] for driver in drivers}
    assert by_bit == {3: "X", 2: "Z", 1: "0", 0: "1"}
