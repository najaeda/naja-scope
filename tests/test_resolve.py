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
