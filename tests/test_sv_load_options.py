# SPDX-License-Identifier: Apache-2.0
"""load_systemverilog's `defines` and `allow_unknown_designs` passthrough.

Added alongside the core-v-mcu exploration: that design needs both --
`` `protect``/`` `endprotect`` wrapped IP needs empty defines to strip, and a
dozen undelivered technology hard macros need blackboxing -- and neither
kwarg was wired past loader.py before, even though the raw
NLDB.loadSystemVerilog binding already accepted them (mirroring load_verilog's
existing allow_unknown_designs).
"""
import pytest

from naja_scope import api
from naja_scope.errors import ScopeError
from naja_scope.session import SESSION


def test_allow_unknown_designs_blackboxes_unresolved_module(tmp_path):
    (tmp_path / "top.sv").write_text(
        "module top(input clk, output q);\n"
        "  unknown_ip u_ip(.clk_i(clk), .q_o(q));\n"
        "endmodule\n")
    SESSION.reset()
    with pytest.raises(ScopeError):
        api.load_systemverilog(files=[str(tmp_path / "top.sv")])
    SESSION.reset()
    res = api.load_systemverilog(files=[str(tmp_path / "top.sv")],
                                 allow_unknown_designs=True)
    assert res["top"]["name"] == "top"


def test_defines_select_ifdef_branch(tmp_path):
    (tmp_path / "top.sv").write_text(
        "module top(input clk, output q);\n"
        "`ifdef USE_WIDE\n"
        "  reg [7:0] r;\n"
        "`else\n"
        "  reg [3:0] r;\n"
        "`endif\n"
        "  always @(posedge clk) r <= r + 1;\n"
        "  assign q = r[0];\n"
        "endmodule\n")
    SESSION.reset()
    api.load_systemverilog(files=[str(tmp_path / "top.sv")],
                           defines=["USE_WIDE"])
    card = api.get_module_card("top")
    reg_models = card["counts"]["by_model"]
    assert any("8" in name or "w8" in name for name in reg_models), reg_models
