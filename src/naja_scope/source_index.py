# SPDX-License-Identifier: Apache-2.0
"""Source range value type.

A netlist object's SystemVerilog origin is read on demand from its raw SNL
`getSourceLoc()` (naja #389/#390) wherever a tool needs it — no prebuilt
index, no eager netlist walk. This module is just the small `SrcRange`
value object that carries one `file:start-end` span. (An earlier version walked
every design at load/snapshot time to build a name-keyed index; that pass was
removed once `getSourceLoc()` proved cheap and snapshot-stable per object.)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


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

    @staticmethod
    def from_loc(loc: Tuple[str, int, int, int, int]) -> "SrcRange":
        # loc is snl.source_loc order: (file, line, end_line, column, end_column)
        return SrcRange(*loc)
