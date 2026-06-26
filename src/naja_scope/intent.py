# SPDX-License-Identifier: Apache-2.0
"""Phase-2 living-intent layer (DESIGN.md "Phase 2", docs/phase2-plan.md §4 P2.0).

A SEPARATE pyslang re-elaboration of the same design, kept alive beside the SNL
session, answering the intent-class questions that are *lost in lowering* —
enum/typedef type names and their members, and symbolic parameter expressions
(formula lost, value kept). This is DESIGN.md "Exposure options" route 1
(prototype): zero naja C++, the productizable coupling (option 2 / NAJAEDA_NOTES
Proposal B) is P2.2 and waits behind this prototype's eval gate.

Route-1 decision (2026-06-25): naja's slang is plain upstream master
(github.com/najaeda/slang HEAD = a merge of MikePopoloski/master, no semantic
fork patches), so PyPI pyslang differs only by released-version drift. The gate
questions are *declaration-level* (enum members, param initializer text,
register->type) which is robust to that drift and to elaboration-hierarchy
divergence — the divergence risk the plan flagged bites instance-coupling
(P2.2's exact bimap), not this. Validated end to end on cva6-privlvl-enum:
priv_lvl_q @ csr_regfile.sv:248 -> riscv::priv_lvl_t -> {M,HS,S,U} in ~3s.

Snapshot asymmetry (DESIGN.md §"Snapshot asymmetry"): a Compilation is never
serializable, so intent is WARM-ONLY. Re-elaboration is cheap (a few seconds in
slang) but must run from the original flist/files — it cannot ride the naja-if
snapshot. Cold start (snapshot-loaded SNL, no flist) degrades to
"intent layer not loaded".

Binding is name-keyed: naja-scope paths use the same SV instance/object names
as slang's elaborated hierarchy, so a path descends the slang tree directly.
Anonymous lowered primitives (#<id>) have no slang name and are not resolvable
here (they are post-lowering artifacts, not source intent). The exact lossy
range bimap is P2.2's job, not the prototype's.
"""
from __future__ import annotations

import os
from typing import List, Optional

from .errors import ScopeError


class IntentUnavailable(ScopeError):
    """Raised when an intent query is made but the living AST is not loaded."""


class IntentProvider:
    """Owns a live pyslang Compilation (warm-only). Lazily elaborated.

    Plugs in beside StructuralProvider (session.Session) per DESIGN.md prep
    hook 2. Holds the Driver + Compilation alive for the session lifetime so the
    raw symbol pointers stay valid.
    """

    def __init__(self, files: Optional[List[str]] = None,
                 flist: Optional[str] = None, top: Optional[str] = None,
                 env: Optional[dict] = None):
        self.files = list(files or [])
        self.flist = flist
        self.top = top
        self.env = dict(env or {})
        self._driver = None
        self._comp = None
        self._sm = None

    # -- elaboration ---------------------------------------------------------

    def ensure(self):
        """Build the pyslang Compilation if not already built. Idempotent."""
        if self._comp is not None:
            return
        try:
            import pyslang  # noqa: F401
            from pyslang.driver import Driver
        except ImportError as e:  # pragma: no cover - env guard
            raise IntentUnavailable(
                "pyslang is not installed; the intent layer is unavailable "
                "(pip install pyslang). Source range is still provided by "
                "get_source.") from e

        # Set the provider's declared elaboration env authoritatively: it must
        # re-elaborate the SAME config naja lowered. setdefault would silently
        # inherit a stale value already in the process (e.g. a different
        # TARGET_CFG), diverging the intent layer from the SNL — a gate failure
        # per docs/phase2-plan.md §4, so make it impossible.
        for k, v in self.env.items():
            os.environ[k] = v

        d = Driver()
        d.addStandardArgs()
        # parseCommandLine treats the first token as argv[0] (program name).
        argline = "slang"
        if self.top:
            argline += f" --top {self.top}"
        d.parseCommandLine(argline)
        if self.flist:
            # The SAME flist naja elaborated; slang expands ${VAR} from env.
            d.processCommandFiles(self.flist, True, False)
        if self.files:
            for f in self.files:
                d.sourceLoader.addFiles(f)
        d.processOptions()
        d.parseAllSources()
        comp = d.createCompilation()
        # Force diagnostics to surface elaboration (so symbols are resolved).
        comp.getAllDiagnostics()
        self._driver = d
        self._comp = comp
        self._sm = d.sourceManager

    @property
    def loaded(self) -> bool:
        return self._comp is not None

    # -- source-location helper ---------------------------------------------

    def _floc(self, loc) -> Optional[str]:
        try:
            fn = self._sm.getFileName(loc)
            ln = self._sm.getLineNumber(loc)
            return f"{os.path.basename(fn)}:{ln}"
        except Exception:
            return None

    # -- symbol resolution (name-keyed hierarchy descent) -------------------

    def _resolve_symbol(self, ref: str):
        """Descend the slang elaborated tree by the dotted SV-name path.

        Returns the leaf Symbol, or raises ScopeError with a precise reason.
        Anonymous (#id) segments are post-lowering artifacts with no slang name.
        """
        self.ensure()
        import pyslang
        from pyslang.ast import InstanceSymbol

        # Package-qualified ref (pkg::name) — for elaboration-time constants and
        # types that live in a package, not the instance hierarchy.
        if "::" in ref:
            pkgname, _, member = ref.partition("::")
            pkg = self._comp.getPackage(pkgname)
            if pkg is None:
                raise ScopeError(f"intent: no package {pkgname!r} (in {ref!r})")
            sym = None
            try:
                sym = pkg.find(member)
            except Exception:
                sym = None
            if sym is None:
                raise ScopeError(
                    f"intent: {member!r} not found in package {pkgname!r}")
            return sym

        segs = [s for s in ref.split(".") if s]
        if not segs:
            raise ScopeError(f"Empty intent reference: {ref!r}")
        if any(s.startswith("#") for s in segs):
            raise ScopeError(
                f"{ref!r} contains an anonymous lowered segment (#id); these "
                "are post-lowering primitives with no source-intent symbol. "
                "Use a named register/instance path.")

        tops = list(self._comp.getRoot().topInstances)
        if not tops:
            raise IntentUnavailable("no top instance in the slang compilation")
        top = next((t for t in tops if t.name == segs[0]), tops[0])
        rest = segs[1:] if segs[0] == top.name else segs

        scope = top.body
        sym = top
        for seg in rest:
            child = None
            try:
                child = scope.find(seg)
            except Exception:
                child = None
            if child is None:
                where = sym.name or "<top>"
                raise ScopeError(
                    f"intent: '{seg}' not found under '{where}' while "
                    f"resolving {ref!r} (not a source-named symbol?)")
            sym = child
            if isinstance(child, InstanceSymbol):
                scope = child.body
            elif getattr(child, "isScope", False):  # property, not a method
                scope = child
        return sym

    # -- public queries ------------------------------------------------------

    def get_type(self, ref: str) -> dict:
        """Resolve the declared type of a value (net/var/port/param)."""
        sym = self._resolve_symbol(ref)
        return self._type_record(ref, sym)

    def get_fsm_states(self, ref: str) -> dict:
        """Enum members + encodings for an enum-typed register (the FSM-state
        / package-typedef-enum gate). Errors clearly if the ref is not enum."""
        sym = self._resolve_symbol(ref)
        rec = self._type_record(ref, sym)
        if "enum" not in rec:
            rec["note"] = (f"{ref} is not enum-typed "
                           f"(type {rec.get('type', '?')}); no FSM states.")
        return rec

    def get_parameters(self, ref: str, symbolic: bool = True) -> dict:
        """Parameters of an instance/module, with their SYMBOLIC initializer
        text (lost in lowering) alongside the elaborated value (kept).

        Includes both parameter ports and body localparams — the latter
        (e.g. `localparam W = $clog2(...)`) are exactly the derived widths whose
        formula lowering throws away."""
        import pyslang
        from pyslang.ast import InstanceSymbol
        sym = self._resolve_symbol(ref)
        if isinstance(sym, InstanceSymbol):
            body = sym.body
        elif sym.kind == pyslang.ast.SymbolKind.InstanceBody:
            body = sym
        else:
            raise ScopeError(
                f"{ref!r} is a {sym.kind!s}, not an instance/module; "
                "get_parameters expects an instance path.")
        params = [self._param_record(m, symbolic) for m in body
                  if getattr(m, "kind", None) == pyslang.ast.SymbolKind.Parameter]
        return {"ref": ref, "module": getattr(body.definition, "name", None),
                "parameters": params, "count": len(params)}

    def describe(self, ref: str) -> dict:
        """Auto-dispatch: resolve the ref and return the record that fits its
        kind — a parameter's symbolic value, a value's type (+ enum members),
        or an instance's parameter list. Backs get_intent(want="auto")."""
        import pyslang
        from pyslang.ast import InstanceSymbol, SymbolKind
        sym = self._resolve_symbol(ref)
        if isinstance(sym, InstanceSymbol) or sym.kind == SymbolKind.InstanceBody:
            return {"intent": "parameters", **self.get_parameters(ref)}
        if sym.kind == SymbolKind.Parameter:
            return {"intent": "parameter", "ref": ref,
                    **self._param_record(sym, symbolic=True)}
        return {"intent": "type", **self._type_record(ref, sym)}

    # -- record builders -----------------------------------------------------

    def _type_record(self, ref: str, sym) -> dict:
        import pyslang
        t = getattr(sym, "type", None)
        if t is None:
            return {"ref": ref, "kind": str(sym.kind),
                    "label": sym.name, "src": self._floc(sym.location),
                    "note": f"{sym.name} is a {sym.kind!s}; no value type."}
        canon = t.canonicalType
        rec = {
            "ref": ref,
            "label": sym.name,
            "type": str(t),                      # e.g. "riscv::priv_lvl_t"
            "canonical_kind": type(canon).__name__,
            "src": self._floc(sym.location),
        }
        if isinstance(canon, pyslang.ast.EnumType):
            width, members = _enum_members(canon)
            rec["enum"] = {
                "width": width,
                "decl": self._floc(canon.location),
                "members": [{"name": n, "encoding": e} for n, e in members],
            }
        return rec

    def _param_record(self, p, symbolic: bool) -> dict:
        rec = {"name": p.name, "value": _const_str(p.value),
               "src": self._floc(p.location)}
        if symbolic:
            rec["expr"] = _param_expr_text(p)
            rec["localparam"] = bool(getattr(p, "isLocalParam", False))
        return rec


# -- module-level helpers -----------------------------------------------------

def _const_str(cv) -> str:
    try:
        return str(cv)
    except Exception:
        return "?"


def _enum_members(enum_t):
    """[(name, encoding)] zero-padded to the enum's declared bit width."""
    bt = enum_t.baseType
    width = getattr(bt, "bitWidth", 0) or getattr(
        getattr(bt, "canonicalType", bt), "bitWidth", 0)
    out = []
    for m in enum_t:
        n = _const_int(m.value)
        if n is not None and width:
            enc = f"{width}'b{n & ((1 << width) - 1):0{width}b}"
        else:
            enc = _const_str(m.value)
        out.append((m.name, enc))
    return width, out


def _const_int(cv):
    """Best-effort Python int from a slang ConstantValue (SVInt)."""
    try:
        iv = cv.value          # SVInt
    except Exception:
        iv = cv
    for conv in (lambda x: int(x), lambda x: x.convertToInt()):
        try:
            return conv(iv)
        except Exception:
            continue
    # last resort: parse the str form (e.g. "2'b11", "3")
    s = str(cv)
    try:
        if "'b" in s:
            return int(s.split("'b", 1)[1].replace("_", ""), 2)
        if "'h" in s:
            return int(s.split("'h", 1)[1].replace("_", ""), 16)
        if "'d" in s:
            return int(s.split("'d", 1)[1].replace("_", ""), 10)
        return int(s)
    except Exception:
        return None


def _param_expr_text(p) -> Optional[str]:
    """The parameter's source initializer text (the symbolic formula).

    Prefer the elaborator-attached `initializer` expression syntax; fall back to
    the declarator `syntax`. Both are textual (pre-evaluation), which is the
    whole point: the formula slang keeps but lowering throws away.
    """
    # Prefer the declarator syntax (verbatim source "NAME = EXPR"); the
    # elaborated `initializer` expression often only stringifies to an opaque
    # repr (e.g. "Expression(ExpressionKind.Conversion)") once type-converted.
    node = getattr(p, "syntax", None)
    if node is None:
        init = getattr(p, "initializer", None)
        node = getattr(init, "syntax", None) if init is not None else None
    if node is None:
        return None
    txt = " ".join(str(node).split()).strip()
    return _strip_to_rhs(txt, p.name).rstrip(";").strip() or None


def _strip_to_rhs(txt: str, name: str) -> str:
    """A declarator may render as "NAME = EXPR"; return EXPR. Robust against
    comparison operators (==, <=, >=, !=) inside the expression."""
    i, n = 0, len(txt)
    while i < n:
        c = txt[i]
        if c == "=":
            prev = txt[i - 1] if i else ""
            nxt = txt[i + 1] if i + 1 < n else ""
            if prev not in "=<>!" and nxt != "=":  # a real assignment '='
                lhs = txt[:i].strip()
                if lhs == name or lhs.endswith(" " + name) or lhs.endswith(name):
                    return txt[i + 1:].strip()
                return txt  # '=' but LHS isn't the name; leave as-is
        i += 1
    return txt
