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

from najaeda import naja, netlist

from .errors import NoDesignError, ScopeError
from .naming import ensure_names
from .source_index import SourceIndex

_SIDECAR_NAME = "naja_scope_source_index.json"
_SIDECAR_META = "naja_scope_session.json"


class Session:
    """Structural provider: live SNL + source index + load metadata."""

    def __init__(self):
        self.source_index: Optional[SourceIndex] = None
        self.source_dirs: List[str] = []
        self.loaded_files: List[str] = []
        self.naming_stats: Optional[dict] = None

    # -- lifecycle -----------------------------------------------------------

    def reset(self):
        netlist.reset()
        self.__init__()

    def has_top(self) -> bool:
        universe = naja.NLUniverse.get()
        return universe is not None and universe.getTopDesign() is not None

    def require_top(self) -> netlist.Instance:
        if not self.has_top():
            raise NoDesignError()
        return netlist.get_top()

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
                           keep_assigns: bool = True) -> netlist.Instance:
        config = netlist.SystemVerilogConfig(
            keep_assigns=keep_assigns, flist=flist, top=top)
        # load_system_verilog exists in 0.5.2 (alias) and 0.7.0 (only name).
        top_instance = netlist.load_system_verilog(files, config=config)
        self._record_sources(files)
        if flist:
            self._record_sources([flist])
        self.naming_stats = ensure_names()
        self.source_index = None  # built lazily on first source query
        return top_instance

    def load_verilog(self, files: List[str], keep_assigns: bool = True,
                     allow_unknown_designs: bool = False) -> netlist.Instance:
        config = netlist.VerilogConfig(
            keep_assigns=keep_assigns,
            allow_unknown_designs=allow_unknown_designs)
        top_instance = netlist.load_verilog(files, config=config)
        self._record_sources(files)
        self.naming_stats = ensure_names()
        self.source_index = None
        return top_instance

    # -- source index --------------------------------------------------------

    def get_source_index(self) -> SourceIndex:
        self.require_top()
        if self.source_index is None:
            self.source_index = SourceIndex.build(netlist.get_top())
        return self.source_index

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
        netlist.dump_naja_if(directory)
        index = self.get_source_index()
        index.save(os.path.join(directory, _SIDECAR_NAME))
        import json
        with open(os.path.join(directory, _SIDECAR_META), "w",
                  encoding="utf-8") as f:
            json.dump({"source_dirs": self.source_dirs,
                       "loaded_files": self.loaded_files}, f)
        return {"path": directory, "source_index": index.stats()}

    def load_snapshot(self, directory: str) -> netlist.Instance:
        if not os.path.isdir(directory):
            raise ScopeError(f"Snapshot directory not found: {directory}")
        try:
            netlist.load_naja_if(directory)
        except RuntimeError as e:
            if "model not found" in str(e):
                raise ScopeError(
                    f"naja-if reload failed: {e}. Known najaeda 0.5.2 issue: "
                    "snapshots of SystemVerilog-loaded designs do not "
                    "round-trip (see NAJAEDA_NOTES.md). Re-elaborate with "
                    "load_systemverilog instead.")
            raise
        self.naming_stats = ensure_names()
        sidecar = os.path.join(directory, _SIDECAR_NAME)
        self.source_index = SourceIndex.load(sidecar) if os.path.isfile(
            sidecar) else None
        meta_path = os.path.join(directory, _SIDECAR_META)
        if os.path.isfile(meta_path):
            import json
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            self.source_dirs = meta.get("source_dirs", [])
            self.loaded_files = meta.get("loaded_files", [])
        return self.require_top()


SESSION = Session()
