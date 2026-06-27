# SPDX-License-Identifier: Apache-2.0
"""Phase-2 living-intent layer — thin client over naja's in-engine SNL↔slang link.

Recovers the source-level facts erased by SystemVerilog lowering — enum/FSM state
names + encodings, declared type names, and symbolic parameter expressions — by
calling naja's curated intent API (`naja.intent_type_of` / `intent_parameters_of`
/ `intent_package_member`). Those walk the live slang AST *in C++*, over the
SNL↔slang bimap naja built at lowering time (`keep_ast_link=True`), and return
plain Python data. There is NO pyslang here and no second elaboration: naja owns
the one AST and answers in dicts (DESIGN.md "Exposure options" option 2; the
naja-side spec is docs/naja-feature-request-slang-coupling.md).

Warm-only (DESIGN.md "Snapshot asymmetry"): the link exists only while the slang
Compilation is alive in-process — i.e. after a SystemVerilog load with
`keep_ast_link`. `naja.intent_available()` reports it. A cold snapshot load has no
Compilation, so intent degrades to "not loaded" until a warm (re)load; the exact
relink-after-snapshot tier is deferred.

Resolution rides naja-scope's structural resolver: a ref is resolved to its SNL
object (`resolve.py`), then handed to `naja.intent_*`. This is why anonymous
lowered primitives (`#<id>`) now answer — they resolve to the FF instance, which
the bimap maps back to its declaring source symbol. Package members (`pkg::name`)
have no SNL object and go through the name-keyed `naja.intent_package_member`.
"""
from __future__ import annotations

from najaeda import naja

from .errors import ScopeError
from .resolve import resolve_path


class IntentUnavailable(ScopeError):
    """Raised when an intent query is made but the live AST link is absent."""


class IntentProvider:
    """Query client over naja's curated intent API, bound to a Session for
    structural ref→object resolution.

    Stateless beyond the session handle: the live AST is owned by naja (kept
    alive by `keep_ast_link`), so "loaded" is simply `naja.intent_available()`.
    Plugs into Session as the IntentProvider seam (DESIGN.md prep hook 2).
    """

    def __init__(self, session):
        self.session = session

    @property
    def loaded(self) -> bool:
        return bool(naja.intent_available())

    # -- public queries ------------------------------------------------------

    def get_type(self, ref: str) -> dict:
        """Declared type of a value (net/term), incl. enum members+encodings."""
        if "::" in ref:
            return self._package_record(ref)
        resolved = resolve_path(self.session, ref)[0]
        rec = naja.intent_type_of(self._intent_obj(resolved))
        if rec is None:
            return {"ref": ref, "label": resolved.path.split(".")[-1],
                    "note": (f"no source type recovered for {ref} (non-enum "
                             "scalar, or no source symbol for this object).")}
        rec["ref"] = ref
        return rec

    def get_fsm_states(self, ref: str) -> dict:
        """Enum members+encodings for an enum-typed register (the FSM-state /
        package-typedef-enum gate). Notes clearly when the ref is not enum."""
        rec = self.get_type(ref)
        if "enum" not in rec:
            rec.setdefault("note", (f"{ref} is not enum-typed "
                                    f"(type {rec.get('type', '?')}); no FSM states."))
        return rec

    def get_parameters(self, ref: str, symbolic: bool = True) -> dict:
        """Parameters + localparams of an instance/module, with their SYMBOLIC
        initializer text (lost in lowering) alongside the elaborated value."""
        rec = naja.intent_parameters_of(self._resolve_instance_obj(ref))
        if rec is None:
            raise ScopeError(
                f"{ref!r}: no parameters recovered (not an instance/module with "
                "a source symbol, or the intent layer is not loaded).")
        rec["ref"] = ref
        return rec

    def describe(self, ref: str) -> dict:
        """Auto-dispatch on the ref's kind, matching get_intent(want='auto')."""
        if "::" in ref:
            return {"intent": "parameter", **self._package_record(ref)}
        resolved = resolve_path(self.session, ref)[0]
        if resolved.kind == "instance":
            return {"intent": "parameters", **self.get_parameters(ref)}
        return {"intent": "type", **self.get_type(ref)}

    # -- resolution helpers --------------------------------------------------

    def _intent_obj(self, resolved):
        """The SNL object to hand to naja.intent_type_of for a resolved ref:
        the raw net/term, or — for an instance — its SNLInstance (top: design)."""
        if resolved.kind == "instance":
            node = resolved.obj
            return node.design if node.is_top else node.snl_instance
        return resolved.obj  # raw SNL net/term (or selected bit)

    def _resolve_instance_obj(self, ref: str):
        """SNLInstance / SNLDesign for a parameters query. Falls back to a bare
        module name not present in the instance hierarchy."""
        try:
            node = resolve_path(self.session, ref, kind="instance")[0].obj
            return node.design if node.is_top else node.snl_instance
        except ScopeError:
            from . import snl
            design = snl.find_design(ref)
            if design is None:
                raise
            return design

    def _package_record(self, ref: str) -> dict:
        """A package member (pkg::name) — name-keyed over the live compilation,
        since packages are not instantiated and have no SNL object."""
        pkg, _, member = ref.partition("::")
        rec = naja.intent_package_member(pkg, member)
        if rec is None:
            raise ScopeError(
                f"intent: {member!r} not found in package {pkg!r} (or the intent "
                f"layer is not loaded) — {ref!r}")
        rec["ref"] = ref
        return rec
