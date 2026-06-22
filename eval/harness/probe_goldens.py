# SPDX-License-Identifier: Apache-2.0
"""Ground-truth probe for the config-dependent CVA6 numeric goldens.

Loads a naja-if snapshot and computes, directly from the elaborated netlist via
the naja-scope api + raw snl traversal, every numeric/any_of golden in
eval/questions/cva6.yaml that can shift between cv32a6_imac_sv32 (dev) and
cv64a6_imafdc_sv39 (headline). Run against either snapshot to derive truth.

Usage: probe_goldens.py <snapshot_dir>
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "src"))

from naja_scope import api, snl  # noqa: E402


def _model_label(name):
    return name or "(unnamed)"


def count_leaf_model(design, target, memo):
    """Flattened count of leaf instances whose model name == target under design."""
    mid = design.getID()
    key = (mid, target)
    if key in memo:
        return memo[key]
    memo[key] = 0  # guard recursion (shouldn't recurse on self for DAG)
    total = 0
    for child in design.getInstances():
        model = child.getModel()
        if model.isAssign():
            continue
        if model.isLeaf():
            if _model_label(model.getName()) == target:
                total += 1
        else:
            total += count_leaf_model(model, target, memo)
    memo[key] = total
    return total


def model_of_path(path):
    matches = api.resolve_path(api.SESSION, path, kind="instance")
    return matches[0].obj.design


def main():
    snap = sys.argv[1]
    api.load_snapshot(snap)
    out = {}

    # flat_sequential counts
    out["cva6-ex-seq-count"] = api.get_stats("ex_stage_i")["flat_sequential"]
    out["cva6-core-seq-count"] = api.get_stats()["flat_sequential"]
    out["cva6-commit-no-regs"] = api.get_stats("commit_stage_i")["flat_sequential"]

    # serdiv naja_fa full-adder count (flattened under the i_div instance's model)
    div_model = model_of_path("ex_stage_i.i_mult.i_div")
    out["_serdiv_model"] = _model_label(div_model.getName())
    out["cva6-serdiv-adders"] = count_leaf_model(div_model, "naja_fa", {})

    # serdiv state_q FSM width: inspect the driver of state_q
    try:
        drv = api.get_drivers("ex_stage_i.i_mult.i_div.state_q")
        out["cva6-div-state-driver"] = drv
    except Exception as e:
        out["cva6-div-state-driver_err"] = f"{type(e).__name__}: {e}"

    # hpdcache_mux uniquified variants
    names = snl.design_names(include_primitives=False)
    mux_variants = sorted(n for n in names
                          if n == "hpdcache_mux" or n.startswith("hpdcache_mux__"))
    out["cva6-uniquify-mux_count"] = len(mux_variants)
    out["cva6-uniquify-mux_variants"] = mux_variants

    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
