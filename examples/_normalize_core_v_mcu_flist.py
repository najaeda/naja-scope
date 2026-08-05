#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Normalize a fusesoc-generated .vc file list into a flist naja-scope's raw
SystemVerilog frontend understands.

CORE-V-MCU is FuseSoC-managed: file order and include paths for its vendored
IP (cv32e40p, pulp_platform_axi, riscv-dbg, ...) come from a generated file
list, not a flat directory. fusesoc's `default` target emits Verilator-
specific directives (--cc, --top-module, -CFLAGS, ...) alongside the
+incdir+/+define+/file-path lines any flist consumer needs. This keeps only
the latter, absolutizing paths relative to the .vc's own directory, and
appends the defines CORE-V-MCU needs that fusesoc's default target doesn't
set: VERILATOR (a few RTL files branch on it) and empty protect/endprotect,
to strip an encrypted-IP `protect`/`endprotect` wrapper in
rtl/efpga/ql_fcb/rtl/fcb.sv that naja's preprocessor can't otherwise parse.

Usage: _normalize_core_v_mcu_flist.py <fusesoc.vc> <out.flist>
"""
import os
import sys


def normalize(vc_path):
    base_dir = os.path.dirname(vc_path)

    def absolutize(path_text):
        return path_text if os.path.isabs(path_text) else os.path.normpath(
            os.path.join(base_dir, path_text))

    lines = []
    with open(vc_path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("+incdir+"):
                lines.append("+incdir+" + absolutize(line[len("+incdir+"):]))
            elif line.startswith("+define+"):
                lines.append(line)
            elif line.startswith("-D") and len(line) > 2:
                lines.append("+define+" + line[2:])
            elif line.endswith((".sv", ".v", ".svh", ".vh")):
                lines.append(absolutize(line))
    return lines


def main():
    if len(sys.argv) != 3:
        sys.exit(f"usage: {sys.argv[0]} <fusesoc.vc> <out.flist>")
    vc_path, out_path = sys.argv[1], sys.argv[2]
    lines = normalize(vc_path)
    lines += ["+define+VERILATOR", "+define+protect=", "+define+endprotect="]
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {len(lines)} lines to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
