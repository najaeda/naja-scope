# SPDX-License-Identifier: Apache-2.0
"""Cross-hierarchy cone regression on CVA6 (cv32a6_imac_sv32).

The motivating case for the SNLLogicalCone redesign: the serial divider's
next-state `state_d` fan-in cone must, in ONE call, surface stop-at-flops
frontier registers OUTSIDE the EX stage (csr_regfile, issue_stage scoreboard) —
a core-global gating dependency a textual grep of serdiv.sv cannot reveal.

Slow (~30s snapshot reload) and gated on the eval snapshot being present, so the
fast unit suite skips it. Named test_zzz_* to run last: it resets the universe
to load CVA6, which would invalidate the session-scoped UART fixture.
Requires najaeda 0.7.6+ (gate combinatorial modeling); on 0.7.5 the cone stops
at logic-gate black boxes and never reaches the cross-hier frontier.
"""
import os

import pytest

from naja_scope import api

_SNAP = os.path.join(os.path.dirname(__file__), "..", "eval", ".cache",
                     "cva6-small", "snapshot")

pytestmark = pytest.mark.skipif(
    not os.path.isfile(os.path.join(_SNAP, "snl.mf")),
    reason="cva6-small snapshot absent (eval/.cache); skipping slow cone regression")


@pytest.fixture(scope="module")
def cva6_session():
    api.SESSION.reset()
    api.load_snapshot(_SNAP)
    yield api.SESSION
    api.SESSION.reset()


def test_div_state_cone_crosses_hierarchy(cva6_session):
    out = api.trace_cone("cva6.ex_stage_i.i_mult.i_div.state_d", "fanin",
                         max_frontier=200)
    # Native cone crosses logic gates now: no opaque-gate black boxes remain.
    assert out["frontier"]["blackbox_count"] == 0
    assert out["counts_by_kind"].get("flop", 0) >= 1

    ch = out["cross_hierarchy"]
    assert ch["root_subtree"] == "cva6.ex_stage_i"
    outside = ch["outside_root_subtree"]
    # The cone reaches register state outside EX — the whole point.
    assert outside["count"] > 0
    assert "cva6.csr_regfile_i" in outside["subtrees"]
    assert "cva6.issue_stage_i" in outside["subtrees"]

    # The verified golden registers appear by name in the flop frontier.
    flop_paths = " ".join(f["path"] for f in out["frontier"]["flops"])
    assert "csr_regfile_i.priv_lvl_q" in flop_paths
    assert "issue_stage_i.i_scoreboard" in flop_paths
