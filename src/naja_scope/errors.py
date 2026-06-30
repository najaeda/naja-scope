# SPDX-License-Identifier: Apache-2.0
"""Structured errors. Tool handlers convert these into error responses with
suggestions instead of opaque tracebacks."""

from __future__ import annotations

from typing import List, Optional


class ScopeError(Exception):
    """Base error carrying an agent-readable message and optional suggestions."""

    def __init__(self, message: str, suggestions: Optional[List[str]] = None):
        super().__init__(message)
        self.message = message
        self.suggestions = suggestions or []

    def to_dict(self) -> dict:
        out = {"error": self.message}
        if self.suggestions:
            out["suggestions"] = self.suggestions
        return out


class NoDesignError(ScopeError):
    def __init__(self):
        super().__init__(
            "No design loaded. Call load_systemverilog / load_verilog / "
            "load_snapshot first."
        )


class ResolveError(ScopeError):
    """Path resolution failure with did-you-mean candidates."""

    def __init__(self, path: str, failed_segment: str,
                 suggestions: Optional[List[str]] = None):
        msg = f"Cannot resolve '{path}': no match for segment '{failed_segment}'."
        super().__init__(msg, suggestions)
        self.path = path
        self.failed_segment = failed_segment
