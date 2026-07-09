# SPDX-License-Identifier: Apache-2.0
"""resolve() is the make-or-break tool: exact, fuzzy, glob, bit selects."""

import pytest

from naja_scope import api
from naja_scope.errors import ResolveError


def test_resolve_instance(uart_session):
    out = api.resolve("uart_top.u_tx")
    kinds = {m["kind"] for m in out["matches"]}
    assert "instance" in kinds
    m = next(m for m in out["matches"] if m["kind"] == "instance")
    assert m["model"].startswith("uart_tx")
    assert m["path"] == "uart_top.u_tx"


def test_resolve_without_top_prefix(uart_session):
    out = api.resolve("u_tx.u_div_cnt")
    assert out["matches"][0]["path"] == "uart_top.u_tx.u_div_cnt"


def test_resolve_top_term(uart_session):
    out = api.resolve("uart_top.tx_o", kind="term")
    m = out["matches"][0]
    assert m["dir"] == "output"
    assert m["width"] == 1
    # non-primitive (hierarchical module) port: no role, not even "Other".
    assert "role" not in m


def test_resolve_primitive_pin_role(uart_session):
    """SNLBitTerm.getRole() on a slang-elaborated sequential primitive
    surfaces as describe()'s `role` field (see snl.role_str). Role is a
    per-bit fact: scalar pins (C, RN) carry it directly, a multi-bit bus pin
    (D, Q on a __w2 flop) only carries it bit-selected -- the raw SNLBusTerm
    has no getRole() of its own, so the bare bus resolves with no role key."""
    dffs = [m for m in api.find("*", kind="instance", limit=5000)["matches"]
            if m["model"] == "naja_dffrn__w2"]
    assert dffs, "expected a naja_dffrn__w2 instance in the UART fixture"
    path = dffs[0]["path"]
    assert api.resolve(f"{path}.C")["matches"][0]["role"] == "Clock"
    assert api.resolve(f"{path}.RN")["matches"][0]["role"] == "AsyncReset"
    assert api.resolve(f"{path}.D[0]")["matches"][0]["role"] == "DataInput"
    assert api.resolve(f"{path}.Q[0]")["matches"][0]["role"] == "DataOutput"
    assert "role" not in api.resolve(f"{path}.D")["matches"][0]


def test_resolve_net_bit_select(uart_session):
    out = api.resolve("uart_top.u_tx.shift_q[0]")
    assert any(m["kind"] in ("net", "term") for m in out["matches"])
    m = out["matches"][0]
    assert m.get("bit") == 0


def test_resolve_bus_net(uart_session):
    out = api.resolve("uart_top.u_tx.shift_q", kind="net")
    m = out["matches"][0]
    assert m["width"] == 8


def test_resolve_typo_gives_suggestions(uart_session):
    with pytest.raises(ResolveError) as exc:
        api.resolve("uart_top.u_tx.shift_w")
    assert any("shift" in s for s in exc.value.suggestions)


def test_resolve_glob_last_segment(uart_session):
    out = api.resolve("uart_top.u_tx.u_*cnt")
    paths = {m["path"] for m in out["matches"]}
    assert "uart_top.u_tx.u_div_cnt" in paths
    assert "uart_top.u_tx.u_bit_cnt" in paths


def test_resolve_includes_src(uart_session):
    out = api.resolve("uart_top.u_tx")
    m = out["matches"][0]
    assert "src" in m and "uart.sv" in m["src"]
