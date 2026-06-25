# SPDX-License-Identifier: Apache-2.0
"""Design session: one design per server process (DESIGN.md section 1).

Owns the loaded netlist, the lazily built source index, and the directories
used to resolve relative source paths. This is the StructuralProvider seam
(DESIGN.md phase-1 prep hook 2): phase 2 adds an IntentProvider next to it
without touching tool handlers.
"""

from __future__ import annotations

import os
from typing import List, Optional

from . import loader, snl
from .errors import NoDesignError, ScopeError

_SIDECAR_META = "naja_scope_session.json"


class Session:
    """Structural provider: live SNL + source index + load metadata.

    Phase 2 (DESIGN.md prep hook 2) adds an optional `IntentProvider` next to
    this StructuralProvider: `self.intent`, built by `load_intent`. It is
    warm-only (a slang Compilation is never serializable — see intent.py), so it
    is absent after a cold snapshot load until `load_intent` re-elaborates.
    """

    def __init__(self):
        self.source_dirs: List[str] = []
        self.loaded_files: List[str] = []
        # Inputs captured at elaboration so load_intent can re-elaborate the
        # SAME design in slang (a snapshot does not carry the flist).
        self.load_spec: dict = {}
        self.intent = None  # Optional[intent.IntentProvider]

    # -- lifecycle -----------------------------------------------------------

    def reset(self):
        loader.reset_universe()
        self.__init__()

    def has_top(self) -> bool:
        return snl.has_top()

    def require_top(self) -> "snl.InstNode":
        if not self.has_top():
            raise NoDesignError()
        return snl.top_node()

    def _record_sources(self, files: List[str]):
        self.loaded_files.extend(files)
        for f in files:
            d = os.path.dirname(os.path.abspath(f))
            if d not in self.source_dirs:
                self.source_dirs.append(d)
        cwd = os.getcwd()
        if cwd not in self.source_dirs:
            self.source_dirs.append(cwd)

    def load_systemverilog(self, files: List[str], flist: Optional[str] = None,
                           top: Optional[str] = None,
                           keep_assigns: bool = True) -> "snl.InstNode":
        loader.load_systemverilog(files, flist=flist, top=top,
                                  keep_assigns=keep_assigns)
        self._record_sources(files)
        if flist:
            self._record_sources([flist])
        self.load_spec = {"files": list(files or []), "flist": flist,
                          "top": top}
        return snl.top_node()

    def load_verilog(self, files: List[str], keep_assigns: bool = True,
                     allow_unknown_designs: bool = False) -> "snl.InstNode":
        loader.load_verilog(files, keep_assigns=keep_assigns,
                            allow_unknown_designs=allow_unknown_designs)
        self._record_sources(files)
        self.load_spec = {"files": list(files or []), "flist": None,
                          "top": None}
        return snl.top_node()

    # -- intent layer (phase 2) ----------------------------------------------

    def load_intent(self, flist: Optional[str] = None,
                    files: Optional[List[str]] = None,
                    top: Optional[str] = None,
                    env: Optional[dict] = None) -> "intent.IntentProvider":
        """Build + elaborate the warm-only intent layer (a separate pyslang
        re-elaboration). Falls back to the inputs captured at SNL load, so after
        `load_systemverilog` no arguments are needed; after a cold snapshot
        load the flist/top must be supplied (the snapshot does not carry them).
        """
        from . import intent as intent_mod
        spec = self.load_spec or {}
        provider = intent_mod.IntentProvider(
            files=files if files is not None else spec.get("files"),
            flist=flist if flist is not None else spec.get("flist"),
            top=top if top is not None else spec.get("top"),
            env=env)
        if not provider.flist and not provider.files:
            raise ScopeError(
                "load_intent needs a flist or files to re-elaborate; a cold "
                "snapshot load does not carry them — pass flist=/top=.")
        provider.ensure()
        self.intent = provider
        return provider

    @property
    def intent_available(self) -> bool:
        return self.intent is not None and self.intent.loaded

    # -- source resolution ---------------------------------------------------

    def find_source_file(self, path: str) -> Optional[str]:
        """Resolve a (possibly relative) sv_src_file path against known dirs."""
        if os.path.isabs(path):
            return path if os.path.isfile(path) else None
        for d in self.source_dirs:
            candidate = os.path.join(d, path)
            if os.path.isfile(candidate):
                return candidate
        return path if os.path.isfile(path) else None

    # -- snapshots ------------------------------------------------------------

    def save_snapshot(self, directory: str) -> dict:
        self.require_top()
        loader.dump_naja_if(directory)
        import json
        with open(os.path.join(directory, _SIDECAR_META), "w",
                  encoding="utf-8") as f:
            json.dump({"source_dirs": self.source_dirs,
                       "loaded_files": self.loaded_files,
                       # Persist the elaboration inputs so the warm-only intent
                       # layer can be re-elaborated after a cold snapshot reload
                       # without re-specifying the flist (a Compilation never
                       # serializes — see intent.py).
                       "load_spec": self.load_spec}, f)
        return {"path": directory}

    def load_snapshot(self, directory: str) -> "snl.InstNode":
        if not os.path.isdir(directory):
            raise ScopeError(f"Snapshot directory not found: {directory}")
        loader.load_naja_if(directory)
        meta_path = os.path.join(directory, _SIDECAR_META)
        if os.path.isfile(meta_path):
            import json
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            self.source_dirs = meta.get("source_dirs", [])
            self.loaded_files = meta.get("loaded_files", [])
            self.load_spec = meta.get("load_spec", {}) or {}
        return self.require_top()


SESSION = Session()
