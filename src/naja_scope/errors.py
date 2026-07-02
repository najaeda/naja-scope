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


# -- SystemVerilog load failures ----------------------------------------------
#
# najaeda's loadSystemVerilog raises three qualitatively different situations
# through one exception path (see loader._classify_sv_load_error): the user's
# RTL is invalid, naja's frontend deliberately doesn't support a construct it
# parsed fine, or something failed that should never happen. Only the first is
# the caller's fault; the agent should treat the other two differently (no
# "fix your code" framing) and point the user at naja-scope's issue tracker.

_NAJA_SCOPE_ISSUES = "https://github.com/najaeda/naja-scope/issues"


class SVSyntaxError(ScopeError):
    """SystemVerilog failed to parse/compile: invalid RTL, not a naja defect."""

    def __init__(self, message: str, diagnostics: Optional[List[dict]] = None):
        super().__init__(message, [
            "Fix the syntax/semantic error(s) reported below at the given "
            "file:line:column.",
        ])
        self.diagnostics = diagnostics or []

    def to_dict(self) -> dict:
        out = super().to_dict()
        if self.diagnostics:
            out["diagnostics"] = self.diagnostics
        return out


class SVUnsupportedError(ScopeError):
    """A construct naja's SystemVerilog frontend recognized but deliberately
    does not translate. A naja feature gap, not an error in the user's RTL."""

    def __init__(self, message: str, unsupported_elements: Optional[List[dict]] = None):
        super().__init__(message, [
            "This hits a known limitation of naja's SystemVerilog frontend, not "
            "an error in your RTL -- rewriting the flagged construct may work "
            "around it. If it's blocking you, let the user know and consider "
            f"opening an issue: {_NAJA_SCOPE_ISSUES}",
        ])
        self.unsupported_elements = unsupported_elements or []

    def to_dict(self) -> dict:
        out = super().to_dict()
        if self.unsupported_elements:
            out["unsupported_elements"] = self.unsupported_elements
        return out


class SVInternalError(ScopeError):
    """Anything else out of the SV load path: not recognizable as a user syntax
    error or a known-unsupported construct. Treat as a naja/naja-scope bug."""

    def __init__(self, message: str):
        super().__init__(message, [
            "This looks like an internal error, not a problem with your RTL. "
            f"Let the user know and open an issue: {_NAJA_SCOPE_ISSUES} "
            "(include the design/snippet that triggered it and this message).",
        ])
        self.internal_error = True

    def to_dict(self) -> dict:
        out = super().to_dict()
        out["internal_error"] = True
        return out
