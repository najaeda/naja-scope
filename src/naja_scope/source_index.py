# SPDX-License-Identifier: Apache-2.0
"""Netlist -> source back-link index.

najaeda (as of 0.5.2) stamps every SNL object with sv_src_* RTL infos during
SystemVerilog lowering but does not expose them through Python bindings; the
only public egress is `dump_verilog(dumpRTLInfosAsAttributes=True)`. So at
index time we dump the annotated Verilog to a temp file once and parse the
`(* sv_src_* *)` attributes back into a dict keyed by (module, kind, name).

This is the interim bridge mandated by CLAUDE.md (public API only). When
najaeda exposes RTL infos directly, only `SourceIndex.build` changes.

Requires the naming pass (naming.ensure_names) to have run first, so that the
names in the dump match the names of the live SNL objects.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class SrcRange:
    file: str
    line: int
    end_line: int
    column: int = 0
    end_column: int = 0

    def to_ref(self) -> str:
        """Compact `file:start-end` form used in tool responses."""
        if self.end_line and self.end_line != self.line:
            return f"{self.file}:{self.line}-{self.end_line}"
        return f"{self.file}:{self.line}"

    def to_json(self) -> list:
        return [self.file, self.line, self.end_line, self.column, self.end_column]

    @staticmethod
    def from_json(data: list) -> "SrcRange":
        return SrcRange(*data)


_ATTR_GROUP_RE = re.compile(r"\(\*\s*(.*?)\s*\*\)")
_ATTR_ITEM_RE = re.compile(r'(\w+)\s*(?:=\s*(?:"([^"]*)"|(-?\d+)))?')
_IDENT = r"(\\\S+|[A-Za-z_][\w$]*)"
_MODULE_RE = re.compile(rf"^\s*module\s+{_IDENT}\s*\(")
_WIRE_RE = re.compile(rf"^\s*wire\s+(?:\[[^\]]+\]\s*)?{_IDENT}\s*;")
_INST_RE = re.compile(rf"^\s*{_IDENT}\s+{_IDENT}\s*\($")
_KEYWORDS = {
    "module", "endmodule", "wire", "reg", "assign", "input", "output",
    "inout", "supply0", "supply1", "parameter", "localparam",
}


def _clean_ident(name: str) -> str:
    return name[1:] if name.startswith("\\") else name


class SourceIndex:
    """sv_src_* ranges keyed by (module_name, kind, object_name)."""

    def __init__(self):
        # kind in {"module", "net", "instance"}; module entries use name "".
        self._ranges: Dict[Tuple[str, str, str], SrcRange] = {}

    def __len__(self) -> int:
        return len(self._ranges)

    def add(self, module: str, kind: str, name: str, rng: SrcRange):
        self._ranges[(module, kind, name)] = rng

    def module_range(self, module: str) -> Optional[SrcRange]:
        return self._ranges.get((module, "module", ""))

    def instance_range(self, module: str, name: str) -> Optional[SrcRange]:
        return self._ranges.get((module, "instance", name))

    def net_range(self, module: str, name: str) -> Optional[SrcRange]:
        return self._ranges.get((module, "net", name))

    # -- construction -------------------------------------------------------

    @staticmethod
    def build(top_instance) -> "SourceIndex":
        """Dump annotated Verilog for the top model and parse it back."""
        from najaeda import netlist

        tmpdir = tempfile.mkdtemp(prefix="naja_scope_src_")
        try:
            dump_path = os.path.join(tmpdir, "design.v")
            config = netlist.VerilogDumpConfig(dumpRTLInfosAsAttributes=True)
            top_instance.dump_verilog(dump_path, config=config)
            return SourceIndex.parse_annotated_verilog(dump_path)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @staticmethod
    def parse_annotated_verilog(path: str) -> "SourceIndex":
        index = SourceIndex()
        pending: Dict[str, object] = {}
        current_module = None
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                groups = _ATTR_GROUP_RE.findall(line)
                if groups:
                    for group in groups:
                        for m in _ATTR_ITEM_RE.finditer(group):
                            key, sval, ival = m.group(1), m.group(2), m.group(3)
                            if key.startswith("sv_src_"):
                                pending[key] = sval if sval is not None else (
                                    int(ival) if ival is not None else None)
                    continue
                stripped = line.strip()
                if not stripped or stripped.startswith("//"):
                    continue
                m = _MODULE_RE.match(line)
                if m:
                    current_module = _clean_ident(m.group(1))
                    index._apply(pending, current_module, "module", "")
                    pending = {}
                    continue
                if current_module:
                    m = _WIRE_RE.match(line)
                    if m:
                        index._apply(pending, current_module, "net",
                                     _clean_ident(m.group(1)))
                        pending = {}
                        continue
                    m = _INST_RE.match(line)
                    if m and _clean_ident(m.group(1)) not in _KEYWORDS:
                        index._apply(pending, current_module, "instance",
                                     _clean_ident(m.group(2)))
                        pending = {}
                        continue
                # Any other statement consumes pending attributes.
                pending = {}
        return index

    def _apply(self, pending: dict, module: str, kind: str, name: str):
        f = pending.get("sv_src_file")
        line = pending.get("sv_src_line")
        if not f or line is None:
            return
        rng = SrcRange(
            file=str(f),
            line=int(line),
            end_line=int(pending.get("sv_src_end_line", line)),
            column=int(pending.get("sv_src_column", 0)),
            end_column=int(pending.get("sv_src_end_column", 0)),
        )
        self.add(module, kind, name, rng)

    # -- stats / persistence -------------------------------------------------

    def stats(self) -> dict:
        kinds: Dict[str, int] = {}
        for (_, kind, _name) in self._ranges:
            kinds[kind] = kinds.get(kind, 0) + 1
        return {"entries": len(self._ranges), "by_kind": kinds}

    def save(self, path: str):
        data = [
            [module, kind, name, rng.to_json()]
            for (module, kind, name), rng in self._ranges.items()
        ]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    @staticmethod
    def load(path: str) -> "SourceIndex":
        index = SourceIndex()
        with open(path, "r", encoding="utf-8") as f:
            for module, kind, name, rng in json.load(f):
                index.add(module, kind, name, SrcRange.from_json(rng))
        return index
