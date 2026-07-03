# SPDX-License-Identifier: Apache-2.0
"""SystemVerilog load-failure classification: syntax vs unsupported vs internal.

najaeda's loadSystemVerilog raises three qualitatively different situations
through one exception path -- see loader._classify_sv_load_error. Only the
first is the caller's fault; naja-scope must not tell an agent to "fix your
RTL" for the other two.
"""
import os

import pytest
from najaeda import naja

from naja_scope import api
from naja_scope.errors import SVInternalError, SVSyntaxError, SVUnsupportedError
from naja_scope.loader import _classify_sv_load_error

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

_HAS_NATIVE_SV_EXCEPTIONS = hasattr(naja, "SystemVerilogSyntaxError")


# -- heuristic fallback (message-text classification) -------------------------
# Exercised directly against synthetic RuntimeErrors so it is deterministic
# regardless of which najaeda build (with or without the typed exceptions
# below) is installed.

def test_classify_syntax_error_by_message():
    exc = RuntimeError(
        "Error while parsing SystemVerilog: SystemVerilog compilation failed:\n"
        "top.sv:2:42: error: expected ';'\n")
    classified = _classify_sv_load_error(exc)
    assert isinstance(classified, SVSyntaxError)
    assert not isinstance(classified, (SVUnsupportedError, SVInternalError))
    assert "internal_error" not in classified.to_dict()


def test_classify_unsupported_by_message():
    exc = RuntimeError(
        "Error while parsing SystemVerilog: Unsupported SystemVerilog elements "
        "encountered (1):\n - top.sv:5:3: Unsupported procedural block")
    classified = _classify_sv_load_error(exc)
    assert isinstance(classified, SVUnsupportedError)
    assert "naja-scope/issues" in classified.suggestions[0]


def test_classify_unrecognized_message_as_internal():
    exc = RuntimeError("Error while parsing SystemVerilog: Internal error: mux width mismatch")
    classified = _classify_sv_load_error(exc)
    assert isinstance(classified, SVInternalError)
    assert classified.to_dict()["internal_error"] is True


# -- native typed exceptions (naja builds that expose them) -------------------

@pytest.mark.skipif(not _HAS_NATIVE_SV_EXCEPTIONS,
                    reason="installed najaeda predates typed SV exceptions")
def test_classify_dispatches_native_types():
    assert isinstance(
        _classify_sv_load_error(naja.SystemVerilogSyntaxError("x")), SVSyntaxError)
    assert isinstance(
        _classify_sv_load_error(naja.SystemVerilogUnsupportedError("x")), SVUnsupportedError)
    assert isinstance(
        _classify_sv_load_error(naja.SystemVerilogInternalError("x")), SVInternalError)


# -- end-to-end through api.load_systemverilog ---------------------------------

def test_load_systemverilog_syntax_error_is_scoped(tmp_path):
    from naja_scope.session import SESSION
    bad = tmp_path / "bad.sv"
    bad.write_text(
        "module top(input clk, output reg [3:0] q)\n"
        "  always @(posedge clk) q <= q + 1\n"
        "endmodule\n")
    SESSION.reset()
    with pytest.raises(SVSyntaxError) as exc_info:
        api.load_systemverilog(files=[str(bad)])
    out = exc_info.value.to_dict()
    assert "internal_error" not in out
    assert "fix" in exc_info.value.suggestions[0].lower()
    # session must stay clean after a rejected load (no half-elaborated top)
    assert not SESSION.has_top()
