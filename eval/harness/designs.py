# SPDX-License-Identifier: Apache-2.0
"""Design registry for the Week-3 eval (DESIGN.md §9).

One entry per design under test. Each entry carries everything BOTH arms need:
- `load`: how arm A's warm naja-scope server elaborates it (files or flist).
- `top`/`env`: elaboration knobs (CVA6 needs CVA6_REPO_DIR / TARGET_CFG /
  HPDCACHE_DIR; see memory `cva6-elaboration-via-naja-scope`).
- `source_root`: the directory arm B (grep baseline) is dropped into and greps.
- `questions`: the YAML golden-answer bank for this design.
- `expect_load_seconds`: rough elaboration cost, for operator sanity only.

Paths are absolute on purpose: the eval is run against specific local checkouts
(uart fixture in-repo; CVA6 at ~/WORK/cva6 — NOT cva6-grenoble, whose hpdcache
submodule is uninitialized).
"""
from __future__ import annotations

import os

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_FIXTURES = os.path.join(_REPO, "tests", "fixtures")
_QDIR = os.path.join(_REPO, "eval", "questions")
# naja-if snapshot cache (gitignored). Since najaeda 0.7.4 fixes SV-snapshot
# reload, a design is elaborated once and reloaded in seconds thereafter — the
# DESIGN.md §5 amortization that lets E2 authoring and E3 re-runs skip the
# 8-68 min CVA6 elaboration.
_CACHE = os.path.join(_REPO, "eval", ".cache")

CVA6_REPO = "/Users/xtof/WORK/cva6"
_CVA6_FLIST = os.path.join(CVA6_REPO, "core", "Flist.cva6")
_HPDCACHE = os.path.join(CVA6_REPO, "core", "cache_subsystem", "hpdcache")


def _cva6_env(target_cfg: str) -> dict:
    return {
        "CVA6_REPO_DIR": CVA6_REPO,
        "TARGET_CFG": target_cfg,
        "HPDCACHE_DIR": _HPDCACHE,
    }


DESIGNS = {
    "uart": {
        "label": "UART (small fixture)",
        "load": {"files": [os.path.join(_FIXTURES, "uart.sv")]},
        "top": None,
        "env": {},
        "source_root": _FIXTURES,
        "questions": os.path.join(_QDIR, "uart.yaml"),
        "expect_load_seconds": 1,
    },
    "cva6-small": {
        "label": "CVA6 cv32a6_imac_sv32 (no FPU)",
        "load": {"flist": _CVA6_FLIST},
        "top": "cva6",
        "env": _cva6_env("cv32a6_imac_sv32"),
        "source_root": CVA6_REPO,
        "questions": os.path.join(_QDIR, "cva6.yaml"),
        "expect_load_seconds": 750,  # measured ~749s first elaboration; ~20s from snapshot
    },
    "cva6-full": {
        "label": "CVA6 cv64a6_imafdc_sv39 (headline)",
        "load": {"flist": _CVA6_FLIST},
        "top": "cva6",
        "env": _cva6_env("cv64a6_imafdc_sv39"),
        "source_root": CVA6_REPO,
        "questions": os.path.join(_QDIR, "cva6.yaml"),
        "expect_load_seconds": 4100,
    },
}


def get(design_key: str) -> dict:
    if design_key not in DESIGNS:
        raise SystemExit(
            f"Unknown design '{design_key}'. Known: {', '.join(DESIGNS)}")
    return DESIGNS[design_key]


def snapshot_dir(design_key: str) -> str:
    """naja-if snapshot cache directory for a design (gitignored)."""
    return os.path.join(_CACHE, design_key, "snapshot")
