# SPDX-License-Identifier: Apache-2.0
"""Netlist -> source back-link index, built from raw SNL source locations.

Since najaeda 0.7.2 every SNL object exposes its SystemVerilog origin through
`getSourceLoc()` (naja #389/#390). We walk the raw designs once and read those
locations directly — no Verilog dump, no attribute reparsing. Entries are keyed
by (module_name, kind, object_name); module entries use name "".

Requires the naming pass (naming.ensure_names) to have run first so that
anonymous instances/nets carry the stable names the tools address them by.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from . import snl


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

    @staticmethod
    def from_loc(loc: Tuple[str, int, int, int, int]) -> "SrcRange":
        # loc is snl.source_loc order: (file, line, end_line, column, end_column)
        return SrcRange(*loc)


class SourceIndex:
    """sv source ranges keyed by (module_name, kind, object_name)."""

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

    # -- construction --------------------------------------------------------

    @staticmethod
    def build() -> "SourceIndex":
        """Walk raw SNL designs and read getSourceLoc() on each object."""
        index = SourceIndex()
        for design in snl.iter_designs(include_primitives=False):
            module = design.getName()
            loc = snl.source_loc(design)
            if loc:
                index.add(module, "module", "", SrcRange.from_loc(loc))
            for inst in design.getInstances():
                loc = snl.source_loc(inst)
                if loc:
                    index.add(module, "instance", inst.getName(),
                              SrcRange.from_loc(loc))
            for net in design.getNets():
                name = net.getName()
                if not name:
                    continue
                loc = snl.source_loc(net)
                if loc:
                    index.add(module, "net", name, SrcRange.from_loc(loc))
        return index

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
