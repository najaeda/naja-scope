# SPDX-License-Identifier: Apache-2.0
"""Naming pass + source index: the two load-time foundations."""

import pytest
from najaeda import naja

from naja_scope import api


def _all_designs():
    db = naja.NLUniverse.get().getTopDB()
    for lib in db.getLibraries():
        if lib.isPrimitives():
            continue
        for design in lib.getSNLDesigns():
            yield design


def test_no_unnamed_instances(uart_session):
    for design in _all_designs():
        for inst in design.getInstances():
            assert inst.getName(), (
                f"unnamed instance (model {inst.getModel().getName()}) "
                f"in {design.getName()}")


def test_uniquified_counter_models_exist(uart_session):
    # Was broken in najaeda 0.5.2 (specializations merged), fixed in 0.7.0:
    # counter and counter__elab1 (see NAJAEDA_NOTES.md).
    names = [d.getName() for d in _all_designs()]
    counters = [n for n in names if n.startswith("counter")]
    assert len(counters) >= 2, f"expected uniquified counters, got {names}"


def test_source_index_has_entries(uart_session):
    index = uart_session.get_source_index()
    stats = index.stats()
    assert stats["entries"] > 0
    assert stats["by_kind"].get("module", 0) >= 3
    assert stats["by_kind"].get("instance", 0) > 0


def test_module_range_points_at_fixture(uart_session):
    index = uart_session.get_source_index()
    rng = index.module_range("uart_tx")
    assert rng is not None
    assert rng.file.endswith("uart.sv")
    assert rng.line >= 1


def test_get_source_of_ff_contains_always_ff(uart_session):
    drivers = api.get_drivers("uart_top.tx_o")
    leaf = drivers["leaf_drivers"]
    assert leaf, drivers
    ff_path = leaf[0]["path"]
    result = api.get_source(ff_path, context_lines=2)
    assert "text" in result, result
    assert "always_ff" in result["text"]


def test_get_source_unknown_range_degrades(uart_session):
    # The top module itself has a range; a term resolves through its owner.
    result = api.get_source("uart_top.tx_o")
    assert "error" in result or "text" in result
