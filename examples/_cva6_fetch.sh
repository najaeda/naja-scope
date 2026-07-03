#!/usr/bin/env bash
# examples/_cva6_fetch.sh — shared setup for the CVA6 demo scripts. Sourced by
# cva6_demo.sh and cva6_demo_agent.sh, not meant to be run directly.
#
# Clones CVA6 at a pinned upstream tag (unless CVA6_REPO_DIR already points at
# a checkout) and exports the env vars naja-scope's flist ${VAR} substitution
# needs. Only the submodules the cv64a6_imafdc_sv39 config actually pulls in
# are initialized (hpdcache for the cache subsystem, cvfpu + its nested
# fpu_div_sqrt_mvp submodule for the F/D FPU) — not the corev_apu/verif/docs
# submodule set, which naja-scope never parses.

CVA6_REF="${CVA6_REF:-v5.3.0}"
CVA6_REPO_URL="${CVA6_REPO_URL:-https://github.com/openhwgroup/cva6.git}"
TARGET_CFG="${TARGET_CFG:-cv64a6_imafdc_sv39}"

if [ -z "${CVA6_REPO_DIR:-}" ]; then
  CVA6_REPO_DIR="$(mktemp -d)/cva6"
  echo "Cloning $CVA6_REPO_URL @ $CVA6_REF into $CVA6_REPO_DIR ..." >&2
  git clone --quiet --depth 1 --branch "$CVA6_REF" "$CVA6_REPO_URL" "$CVA6_REPO_DIR"
  git -C "$CVA6_REPO_DIR" submodule update --init --quiet --depth 1 -- \
    core/cache_subsystem/hpdcache core/cvfpu
  git -C "$CVA6_REPO_DIR/core/cvfpu" submodule update --init --quiet --depth 1 -- \
    src/fpu_div_sqrt_mvp
else
  echo "Using existing CVA6 checkout: $CVA6_REPO_DIR" >&2
fi

export CVA6_REPO_DIR TARGET_CFG
export HPDCACHE_DIR="${HPDCACHE_DIR:-$CVA6_REPO_DIR/core/cache_subsystem/hpdcache}"
