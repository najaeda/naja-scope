# SPDX-License-Identifier: Apache-2.0
"""Identity & source: anonymous lowered instances are addressed by their stable
per-design id (`#<id>`), source ranges come from getSourceLoc() on demand."""

import pytest
from najaeda import naja

from naja_scope import api, snl


def _all_designs():
    db = naja.NLUniverse.get().getTopDB()
    for lib in db.getLibraries():
        if lib.isPrimitives():
            continue
        for design in lib.getSNLDesigns():
            yield design


def test_anonymous_instances_get_id_segments(uart_session):
    """Lowered primitives are anonymous (no eager naming pass); inst_segment
    falls back to `#<id>` and that segment round-trips via getInstanceByID."""
    anon = 0
    for design in _all_designs():
        for inst in design.getInstances():
            seg = snl.inst_segment(inst)
            if not inst.getName():
                anon += 1
                assert seg.startswith("#"), seg
                back = snl.instance_by_segment(design, seg)
                assert back is not None and back.getID() == inst.getID()
            else:
                assert seg == inst.getName()
    assert anon > 0, "expected some anonymous lowered primitives in the UART fixture"


def test_friendly_label_is_readable(uart_session):
    """The registered tx_o flop gets a readable, driven-net-based label even
    though it carries no SV name."""
    drivers = api.get_drivers("uart_top.tx_o")
    leaf = drivers["leaf_drivers"]
    assert leaf, drivers
    entry = leaf[0]
    assert entry["path"].startswith("uart_top.")
    assert "tx_o" in entry["label"], entry


def test_uniquified_counter_models_exist(uart_session):
    # Parameterized instances must keep distinct specializations rather than
    # merging into one shared model: counter and counter__elab1.
    names = [d.getName() for d in _all_designs()]
    counters = [n for n in names if n.startswith("counter")]
    assert len(counters) >= 2, f"expected uniquified counters, got {names}"


def test_module_card_src_points_at_fixture(uart_session):
    """get_module_card resolves the module source range on demand (no index)."""
    card = api.get_module_card("uart_tx")
    assert "src" in card, card
    assert card["src"].split(":")[0].endswith("uart.sv")


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
