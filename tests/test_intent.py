# SPDX-License-Identifier: Apache-2.0
"""Phase-2 intent layer (intent.py): package-typedef enum members + symbolic
parameter expressions, the two capabilities the cva6-privlvl-enum /
symbolic-param eval gates need. Runs on a small self-contained fixture
(intent_mini.sv) and never touches naja's global universe — the IntentProvider
is a separate pyslang re-elaboration, so these tests are independent of the
session-scoped uart fixture."""
import os

import pytest

pytest.importorskip("pyslang")  # warm-only layer; skip where pyslang is absent

from naja_scope import api  # noqa: E402
from naja_scope.errors import ScopeError  # noqa: E402
from naja_scope.intent import IntentProvider  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "intent_mini.sv")


@pytest.fixture(scope="module")
def ip():
    p = IntentProvider(files=[FIXTURE], top="intent_mini")
    p.ensure()
    return p


# -- enum / FSM-state recovery (the package-typedef-enum gate) ---------------

def test_fsm_states_package_typedef_enum(ip):
    rec = ip.get_fsm_states("intent_mini.state_q")
    assert rec["type"] == "mini_pkg::state_e"
    assert rec["enum"]["width"] == 2
    members = {m["name"]: m["encoding"] for m in rec["enum"]["members"]}
    assert members == {"ST_IDLE": "2'b00", "ST_RUN": "2'b01", "ST_DONE": "2'b11"}
    # member decl is in the package, not at the register — the gate's whole point
    assert rec["enum"]["decl"].endswith(".sv:5")
    assert rec["src"].endswith(".sv:22")


def test_get_type_resolves_alias(ip):
    rec = ip.get_type("intent_mini.state_q")
    assert rec["type"] == "mini_pkg::state_e"
    assert rec["canonical_kind"] == "EnumType"


def test_get_fsm_states_non_enum_notes(ip):
    # IDX_W is an int localparam, not enum-typed: no FSM states, but no crash.
    rec = ip.get_fsm_states("intent_mini.IDX_W")
    assert "enum" not in rec


# -- symbolic parameter expressions ------------------------------------------

def test_symbolic_param_ternary_package(ip):
    rec = ip.describe("mini_pkg::PLEN")
    assert rec["intent"] == "parameter"
    assert rec["value"] == "34"
    assert rec["expr"] == "(32 == 32) ? 34 : 56"  # formula kept, not just 34


def test_symbolic_param_clog2_localparam(ip):
    rec = ip.describe("intent_mini.IDX_W")
    assert rec["expr"] == "$clog2(DEPTH)"
    assert rec["value"] == "2"


def test_get_parameters_includes_localparams(ip):
    rec = ip.get_parameters("intent_mini")
    by_name = {p["name"]: p for p in rec["parameters"]}
    assert "DEPTH" in by_name and "IDX_W" in by_name
    assert by_name["IDX_W"]["localparam"] is True
    assert by_name["DEPTH"]["localparam"] is False


# -- error / robustness paths ------------------------------------------------

def test_anonymous_segment_rejected(ip):
    with pytest.raises(ScopeError, match="anonymous"):
        ip.get_type("intent_mini.#7")


def test_unknown_name_rejected(ip):
    with pytest.raises(ScopeError, match="not found"):
        ip.get_type("intent_mini.does_not_exist")


def test_unknown_package_rejected(ip):
    with pytest.raises(ScopeError, match="package"):
        ip.get_type("no_such_pkg::FOO")


# -- api dispatch + graceful degradation -------------------------------------

def test_api_get_intent_degrades_when_unloaded():
    from naja_scope.session import SESSION
    saved = SESSION.intent
    SESSION.intent = None
    try:
        out = api.get_intent("anything")
        assert out["intent_loaded"] is False
        assert "get_source" in out["note"]
    finally:
        SESSION.intent = saved


def test_api_get_intent_dispatch(ip):
    from naja_scope.session import SESSION
    saved = SESSION.intent
    SESSION.intent = ip
    try:
        out = api.get_intent("intent_mini.state_q", want="fsm_states")
        assert out["intent"] == "fsm_states"
        assert out["type"] == "mini_pkg::state_e"
        # bad want -> structured error, not exception
        err = api.get_intent("intent_mini.state_q", want="bogus")
        assert "error" in err
    finally:
        SESSION.intent = saved
