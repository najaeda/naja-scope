# SPDX-License-Identifier: Apache-2.0
"""SyncReset/SyncSet pin-role facts (najaeda 0.7.12).

sync_reset_mini.sv has one `always_ff @(posedge clk) if (rst) ... else ...`
flop -- reset is sampled on the clock edge, not in the sensitivity list, so
its role is SyncReset, distinct from uart.sv's async-reset flops covered in
test_tools.py / test_resolve.py.
"""

import os

import pytest

from naja_scope import api

HERE = os.path.dirname(__file__)
FIXTURE = os.path.join(HERE, "fixtures", "sync_reset_mini.sv")


@pytest.fixture
def sync_reset_session():
    from naja_scope.session import SESSION

    SESSION.reset()
    SESSION.load_systemverilog([FIXTURE])
    yield SESSION


def test_module_card_sync_reset_counts(sync_reset_session):
    card = api.get_module_card("sync_reset_mini")
    assert card["counts"]["sequential_instances"] > 0
    assert card["counts"]["sequential_with_sync_reset"] > 0
    assert card["counts"]["sequential_with_sync_set"] == 0
    # not async: reset isn't in the sensitivity list.
    assert card["counts"]["sequential_with_async_reset"] == 0
    assert card["counts"]["sequential_with_async_set"] == 0


def test_resolve_sync_reset_role(sync_reset_session):
    dffs = [m for m in api.find("*", kind="instance", limit=5000)["matches"]
            if "dff" in m["model"].lower()]
    assert dffs, "expected a synchronous-reset flop instance in the fixture"
    path = dffs[0]["path"]
    matches = api.resolve(f"{path}.*")["matches"]
    roles = {m["path"]: m.get("role") for m in matches if "role" in m}
    assert "SyncReset" in roles.values()
