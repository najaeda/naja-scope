# SPDX-License-Identifier: Apache-2.0
"""Intent layer (intent.py): package-typedef enum members + symbolic
parameter expressions, the two capabilities the cva6-privlvl-enum /
symbolic-param eval cases need.

The intent layer is now a thin client over naja's in-engine SNL↔slang link
(naja.intent_*, retained by keep_ast_link) — no pyslang, no second elaboration.
So these tests load the fixture into the real session WITH the link, query
through it, and restore the shared uart universe on teardown."""
import os

import pytest

from najaeda import naja  # noqa: E402

from naja_scope import api  # noqa: E402
from naja_scope.errors import ScopeError  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
FIXTURE = os.path.join(FIXTURES, "intent_mini.sv")
UART_SV = os.path.join(FIXTURES, "uart.sv")


@pytest.fixture(scope="module")
def ip():
    """intent_mini loaded warm WITH the AST link; yields the IntentProvider.
    Restores the shared uart universe afterwards so later test files are intact."""
    from naja_scope.session import SESSION
    SESSION.reset()
    SESSION.load_systemverilog([FIXTURE], top="intent_mini", keep_ast_link=True)
    if not SESSION.intent_available:
        pytest.skip("naja build without the SNL↔slang link (keep_ast_link)")
    yield SESSION.intent
    SESSION.reset()
    SESSION.load_systemverilog([UART_SV])


# -- enum / FSM-state recovery (the package-typedef-enum gate) ---------------

def test_fsm_states_package_typedef_enum(ip):
    rec = ip.get_fsm_states("intent_mini.state_q")
    assert rec["type"] == "mini_pkg::state_e"
    assert rec["enum"]["width"] == 2
    members = {m["name"]: m["encoding"] for m in rec["enum"]["members"]}
    assert members == {"ST_IDLE": "2'b00", "ST_RUN": "2'b01", "ST_DONE": "2'b11"}
    # member decl is in the package, not at the register — the gate's whole point
    assert rec["enum"]["decl"].endswith(".sv:5")
    assert rec["src"].endswith(".sv:26")


def test_get_type_resolves_alias(ip):
    rec = ip.get_type("intent_mini.state_q")
    assert rec["type"] == "mini_pkg::state_e"
    assert rec["canonical_kind"] == "enum"


def test_get_fsm_states_non_enum_notes(ip):
    # clk is a plain logic net, not enum-typed: no FSM states, but no crash.
    rec = ip.get_fsm_states("intent_mini.clk")
    assert "enum" not in rec
    assert "note" in rec


# -- non-enum types now answer too (naja extended typeOf beyond enums) --------

def test_non_enum_scalar_type(ip):
    # A plain logic value returns its declared type (was None pre-extension).
    rec = ip.get_type("intent_mini.clk")
    assert rec["type"] == "logic"
    assert rec["canonical_kind"] == "scalar"
    assert "enum" not in rec and "struct" not in rec


def test_packed_struct_fields(ip):
    # A packed-struct register exposes its field names + bit ranges (the struct
    # analog of enum members — lost in lowering, recovered via the AST link).
    rec = ip.get_type("intent_mini.req_q")
    assert rec["canonical_kind"] == "packed_struct"
    fields = {f["name"]: f for f in rec["struct"]["fields"]}
    assert set(fields) == {"valid", "id"}
    assert fields["id"]["msb"] == 3 and fields["id"]["lsb"] == 0
    assert rec["struct"]["width"] == 5
    assert rec["struct"]["decl"].endswith(".sv:10")  # the typedef, in the package


# -- anonymous lowered primitive (#<id>) — the route-1 prototype REFUSED this --

def test_anonymous_id_resolves_to_source_enum(ip):
    """A bit-blasted FF (#<id>, no source name) now answers: the bimap maps it
    back to its declaring variable symbol (state_q -> mini_pkg::state_e)."""
    from naja_scope.session import SESSION
    top = SESSION.require_top()
    ff = next(i for i in top.design.getInstances()
              if i.getModel().getName().startswith("naja_dffrn"))
    rec = ip.get_type(f"intent_mini.#{ff.getID()}")
    assert rec["type"] == "mini_pkg::state_e"
    assert rec["enum"]["width"] == 2


# -- symbolic parameter expressions ------------------------------------------

def test_symbolic_param_ternary_package(ip):
    rec = ip.describe("mini_pkg::PLEN")
    assert rec["intent"] == "parameter"
    assert rec["value"] == "34"
    assert rec["expr"] == "(32 == 32) ? 34 : 56"  # formula kept, not just 34


def test_symbolic_param_clog2_localparam(ip):
    # IDX_W is a module localparam — no SNL object of its own, reached via the
    # module's parameter list (not a standalone ref).
    rec = ip.get_parameters("intent_mini")
    idx = next(p for p in rec["parameters"] if p["name"] == "IDX_W")
    assert idx["expr"] == "$clog2(DEPTH)"
    assert idx["value"] == "2"


def test_get_parameters_includes_localparams(ip):
    rec = ip.get_parameters("intent_mini")
    by_name = {p["name"]: p for p in rec["parameters"]}
    assert "DEPTH" in by_name and "IDX_W" in by_name
    assert by_name["IDX_W"]["localparam"] is True
    assert by_name["DEPTH"]["localparam"] is False


# -- param value normalization (sized literal -> plain decimal) --------------

def test_decimal_value_normalization():
    from naja_scope.intent import _decimal_value
    assert _decimal_value("32'd1") == "1"      # the CVA6 REQ_ID_BITS nit
    assert _decimal_value("8'hff") == "255"
    assert _decimal_value("4'b0101") == "5"
    assert _decimal_value("16'so10") == "8"    # signed octal magnitude
    # already-decimal, formulas, and x/z literals pass through untouched
    assert _decimal_value("34") == "34"
    assert _decimal_value("(XLEN == 32) ? 34 : 56") == "(XLEN == 32) ? 34 : 56"
    assert _decimal_value("32'dx") == "32'dx"
    assert _decimal_value(7) == 7


# -- error / robustness paths ------------------------------------------------

def test_unknown_name_rejected(ip):
    with pytest.raises(ScopeError, match="resolve"):
        ip.get_type("intent_mini.does_not_exist")


def test_unknown_package_rejected(ip):
    with pytest.raises(ScopeError, match="package"):
        ip.get_type("no_such_pkg::FOO")


# -- api dispatch + graceful degradation -------------------------------------

def test_api_get_intent_degrades_when_unloaded(monkeypatch):
    from naja_scope import session as sess
    monkeypatch.setattr(sess.naja, "intent_available", lambda: False)
    out = api.get_intent("anything")
    assert out["intent_loaded"] is False
    assert "get_source" in out["note"]


def test_api_get_intent_dispatch(ip):
    out = api.get_intent("intent_mini.state_q", want="fsm_states")
    assert out["intent"] == "fsm_states"
    assert out["type"] == "mini_pkg::state_e"
    # bad want -> structured error, not exception
    err = api.get_intent("intent_mini.state_q", want="bogus")
    assert "error" in err


# -- productization: env opt-in + non-fatal auto-load ------------------------

def test_auto_intent_env_parsing(monkeypatch):
    for v in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv("NAJA_SCOPE_INTENT", v)
        assert api._auto_intent() is True
    for v in ("", "0", "off", "no"):
        monkeypatch.setenv("NAJA_SCOPE_INTENT", v)
        assert api._auto_intent() is False
    monkeypatch.delenv("NAJA_SCOPE_INTENT", raising=False)
    assert api._auto_intent() is False


def test_attach_intent_explicit_raises_env_swallows(monkeypatch):
    # Simulate a cold session (no live link) with no captured load_spec: an
    # explicit intent request must raise; the env opt-in must degrade (best-
    # effort), never failing the load.
    from naja_scope.session import SESSION
    from naja_scope import session as sess
    monkeypatch.setattr(sess.naja, "intent_available", lambda: False)
    saved = SESSION.load_spec
    SESSION.load_spec = {}
    try:
        with pytest.raises(ScopeError):
            api._attach_intent({"top": "x"}, explicit=True)
        monkeypatch.setenv("NAJA_SCOPE_INTENT", "1")
        out = api._attach_intent({"top": "x"}, explicit=False)
        assert out["intent_loaded"] is False
        assert "intent_note" in out
    finally:
        SESSION.load_spec = saved
