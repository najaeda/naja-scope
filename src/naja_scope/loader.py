# SPDX-License-Identifier: Apache-2.0
"""Raw load boundary.

Elaboration, Liberty/primitive loading, and naja-if snapshots, driven directly
through the raw `naja` DB/universe API (NLUniverse / NLDB) rather than the
high-level najaeda.netlist loaders. This keeps naja-scope on the raw layer
end to end; the only remaining high-level surface is the query_python escape
hatch.

The orchestration mirrors what najaeda.netlist does: lazy universe/top-DB
bootstrap, and the `--top` override injected through a temporary flist.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from typing import List, Optional

from najaeda import naja

from .errors import SVInternalError, SVSyntaxError, SVUnsupportedError

# najaeda>=0.7.9 (naja-scope's pinned floor) raises these typed exceptions
# directly from loadSystemVerilog; anything loaded out-of-band below that floor
# (e.g. via NAJAEDA_SRC pointing at an older checkout) only raises plain
# RuntimeError. Detect once so classification degrades gracefully instead of
# hard-depending on the new types.
_NATIVE_SV_SYNTAX = getattr(naja, "SystemVerilogSyntaxError", None)
_NATIVE_SV_UNSUPPORTED = getattr(naja, "SystemVerilogUnsupportedError", None)
_NATIVE_SV_INTERNAL = getattr(naja, "SystemVerilogInternalError", None)

# Fallback heuristics for najaeda builds without the typed exceptions above:
# naja's own message text already separates these cases (see naja core's
# SNLSVConstructor.cpp), it just isn't typed yet. Best-effort only -- the
# wording carries no compatibility guarantee, hence "fallback".
_UNSUPPORTED_MARKER = "Unsupported SystemVerilog element"
_DIAGNOSTIC_LOCATION_RE = re.compile(r":\d+:\d+: error:")


def _classify_sv_load_error(exc: RuntimeError) -> Exception:
    """Map a najaeda SystemVerilog load failure onto a ScopeError subclass so
    the agent (and through it, the end user) can tell "your RTL is invalid"
    apart from "naja doesn't support this" apart from "this is a naja bug"."""
    if _NATIVE_SV_SYNTAX is not None and isinstance(exc, _NATIVE_SV_SYNTAX):
        return SVSyntaxError(str(exc), diagnostics=getattr(exc, "diagnostics", None))
    if _NATIVE_SV_UNSUPPORTED is not None and isinstance(exc, _NATIVE_SV_UNSUPPORTED):
        return SVUnsupportedError(
            str(exc), unsupported_elements=getattr(exc, "unsupported_elements", None))
    if _NATIVE_SV_INTERNAL is not None and isinstance(exc, _NATIVE_SV_INTERNAL):
        return SVInternalError(str(exc))

    message = str(exc)
    if _UNSUPPORTED_MARKER in message:
        return SVUnsupportedError(message)
    if _DIAGNOSTIC_LOCATION_RE.search(message) or "compilation failed" in message:
        return SVSyntaxError(message)
    return SVInternalError(message)


def get_top_db():
    """Lazily bootstrap the universe + top DB, as najaeda.__get_top_db does."""
    if naja.NLUniverse.get() is None:
        naja.NLUniverse.create()
    universe = naja.NLUniverse.get()
    if universe.getTopDB() is None:
        db = naja.NLDB.create(universe)
        universe.setTopDB(db)
    return universe.getTopDB()


def reset_universe():
    u = naja.NLUniverse.get()
    if u is not None:
        u.destroy()


def load_systemverilog(files: List[str], flist: Optional[str] = None,
                       top: Optional[str] = None, keep_assigns: bool = True,
                       keep_ast_link: bool = False):
    db = get_top_db()
    effective_flist = flist
    temp_flist = None
    # Inject --top through a temporary flist, as najaeda does (no raw --top arg).
    if top is not None:
        with tempfile.NamedTemporaryFile(
                "w", suffix=".f", delete=False, encoding="utf-8") as f:
            temp_flist = f.name
            f.write(f"--top {top}\n")
            if flist:
                quoted = flist.replace("\\", "\\\\").replace('"', '\\"')
                f.write(f'-f "{quoted}"\n')
        effective_flist = temp_flist
    try:
        db.loadSystemVerilog(
            files,
            keep_assigns=keep_assigns,
            elaborated_ast_json_path=None,
            diagnostics_report_path=None,
            pretty_print_elaborated_ast_json=True,
            include_source_info_in_elaborated_ast_json=True,
            flist=effective_flist,
            suppress_warnings=None,
            # Retain the live slang Compilation + SNL<->slang bimap for the
            # intent layer (naja.intent_*). Off by default (the Compilation is
            # GB-class on large designs); enabled only when the intent layer is
            # requested.
            keep_ast_link=keep_ast_link,
        )
    except RuntimeError as e:
        raise _classify_sv_load_error(e) from e
    finally:
        if temp_flist and os.path.exists(temp_flist):
            os.remove(temp_flist)


def load_verilog(files: List[str], keep_assigns: bool = True,
                 allow_unknown_designs: bool = False):
    # najaeda>=0.7.11 renamed the raw NLDB.loadVerilog kwarg from
    # allow_unknown_designs to blackbox_unknown_modules; naja-scope's own
    # public parameter name is kept stable across that rename.
    get_top_db().loadVerilog(
        files,
        keep_assigns=keep_assigns,
        blackbox_unknown_modules=allow_unknown_designs,
        preprocess_enabled=False,
        conflicting_design_name_policy="forbid",
    )


def load_liberty(files: List[str]):
    if not files:
        raise Exception("No liberty files provided")
    logging.info("Loading liberty files: %s", ", ".join(files))
    get_top_db().loadLibertyPrimitives(files)


def load_primitives(name: str):
    """Load a primitive library bundled in najaeda (xilinx|yosys) onto raw DB."""
    db = get_top_db()
    if name == "xilinx":
        from najaeda.primitives import xilinx
        xilinx.load(db)
    elif name == "yosys":
        from najaeda.primitives import yosys
        yosys.load(db)
    else:
        raise ValueError(f"Unknown primitives library: {name}")


def load_primitives_from_file(file: str):
    """Exec a user file defining load(db) against the raw top DB."""
    if not os.path.isfile(file):
        raise FileNotFoundError(
            f"Cannot load primitives from non existing file: {file}")
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location("user_primitives", file)
    module = importlib.util.module_from_spec(spec)
    sys.modules["user_primitives"] = module
    spec.loader.exec_module(module)
    if not hasattr(module, "load"):
        raise RuntimeError(f"{file} must define a function named `load(db)`")
    module.load(get_top_db())


def dump_naja_if(path: str):
    get_top_db().dumpNajaIF(path)


def load_naja_if(path: str):
    if not os.path.isdir(path):
        raise FileNotFoundError(
            f"Cannot load Naja IF from non existing directory: {path}")
    logging.info("Loading Naja IF from %s", path)
    naja.NLDB.loadNajaIF(path)
