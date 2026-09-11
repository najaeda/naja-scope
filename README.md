# naja-scope

[![PyPI version](https://img.shields.io/pypi/v/naja-scope.svg)](https://pypi.org/project/naja-scope/)
[![Python versions](https://img.shields.io/pypi/pyversions/naja-scope.svg)](https://pypi.org/project/naja-scope/)
[![CI](https://github.com/najaeda/naja-scope/actions/workflows/ci.yml/badge.svg)](https://github.com/najaeda/naja-scope/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Glama quality](https://glama.ai/mcp/servers/najaeda/naja-scope/badges/score.svg)](https://glama.ai/mcp/servers/najaeda/naja-scope)

**Let your AI assistant explore SystemVerilog designs — without pasting source code into the chat.**

naja-scope is an [MCP](https://modelcontextprotocol.io) server that gives AI
agents (Claude, and any MCP-compatible assistant) a precise, structured view of
your elaborated SystemVerilog design. Instead of dumping thousands of lines of
RTL into the model's context, the agent asks targeted questions — *what drives
this signal? what's inside this module? where does this net come from?* — and
gets back small, exact answers with file-and-line references.

Built on the [najaeda](https://github.com/najaeda/naja) netlist engine.

---

## Why

Large designs don't fit in a chat window. Pasting RTL is slow, expensive, and
the model still can't reliably trace connectivity across hierarchy. naja-scope
turns your design into something an agent can *navigate*:

- 🔎 **Trace connectivity** — find what drives or loads any signal, across
  module boundaries.
- 🌲 **Walk the hierarchy** — explore modules, instances, and ports on demand.
- 🎯 **Jump to source** — every answer comes with `file:line` ranges, so the
  agent can quote the exact RTL that matters.
- 🧩 **Logic cones** — trace fan-in / fan-out combinational cones up to the
  register boundary.
- 💡 **Recover design intent** — enum state names, struct/union fields, and
  parameter formulas that normally vanish when a design is elaborated.

Works on **RTL and gate-level netlists** alike: load elaborated SystemVerilog,
or load a post-synthesis structural Verilog netlist together with its Liberty
standard-cell library and navigate the gates the same way (see
[Gate-level designs](#gate-level-designs)).

All responses are token-bounded: lists paginate, large results truncate with
clear markers. Your context stays small; your answers stay accurate.

---

## Does it actually help?

naja-scope helps most when the answer exists in the elaborated design rather
than in any single source file. In an initial 17-question run on the
`cv32a6_imac_sv32` configuration of
[CVA6](https://github.com/openhwgroup/cva6), the same Claude Code agent was
tested with naja-scope and with source-search tools alone.

| Agent setup | Provider and models | Initial automated score | Turns | Input processed | Output tokens |
|---|---|---:|---:|---:|---:|
| **Agent + naja-scope** | Anthropic Claude Code; `claude-sonnet-4-6` with `claude-haiku-4-5-20251001` helper | **17 / 17** | **77** | **1,058,556** | **19,520** |
| Agent + grep/read source | Anthropic Claude Code; `claude-sonnet-4-6` with `claude-haiku-4-5-20251001` helper | 10 / 17 | 123 | 5,461,719 | 55,962 |

The difference is clearest on structural questions that source search cannot
answer directly:

| CVA6 question | Agent + naja-scope | Agent + grep/read source |
|---|---|---|
| Flattened register groups under `ex_stage_i` | **92**, in 4 turns | No answer at the turn limit |
| Flattened register groups under `commit_stage_i` | **0**, in 3 turns | No answer at the turn limit |
| Elaborated `hpdcache_mux` variants | **20**, in 3 turns | No answer at the turn limit |
| Primitive driving divider `state_q` | **`naja_dffrn__w2`**, in 4 turns | Found the `always_ff`, but not the lowered primitive |

Source search remains the right tool for local textual questions. naja-scope
adds the elaborated hierarchy, connectivity, lowered primitives, and generated
or uniquified structures that are otherwise difficult to reconstruct.

See the [benchmark methodology and multi-model runner](benchmarks/README.md)
and [historical result record](benchmarks/historical-cva6-20260628.json) for
configuration, scoring, token accounting, and reproducibility details.

---

## Install

```sh
pip install naja-scope        # pulls najaeda and the MCP runtime from PyPI
naja-scope-mcp                # stdio MCP server
```

---

## Connect it to Claude Code

```sh
claude mcp add naja-scope -- naja-scope-mcp
```

Or add it to any MCP client's config:

```json
{
  "mcpServers": {
    "naja-scope": {
      "command": "naja-scope-mcp"
    }
  }
}
```

Then just ask your assistant to load a design and start exploring:

> *"Load my UART design from `rtl/uart.sv` with top `uart_top`, then show me
> everything that drives `tx_o`."*

The agent loads the design once and answers follow-up questions instantly — no
re-reading source, no giant pastes.

---

## Connect it to ChatGPT

ChatGPT connects to MCP servers over an **HTTP endpoint** (custom connectors /
Developer mode), so run naja-scope as an HTTP server instead of stdio:

```sh
naja-scope-mcp --transport streamable-http --host 127.0.0.1 --port 8000
```

This serves MCP at `http://<host>:8000/mcp`. Because ChatGPT reaches the server
over the network, expose that URL where ChatGPT can see it — e.g. a public
tunnel for a local run:

```sh
# example: a tunnel to your local server (ngrok, cloudflared, …)
ngrok http 8000        # -> https://<something>.ngrok.app  →  add /mcp
```

Then in ChatGPT, open **Settings → Connectors** (enable Developer mode if
needed), **add a custom connector**, and paste the server URL
(`https://<your-host>/mcp`). Once connected, ask it to load a design and explore
exactly as above. (ChatGPT's connector UI evolves; the constant is: it needs an
HTTPS MCP URL, which `--transport streamable-http` provides.)

> ⚠️ The HTTP server has no built-in auth — only expose it over a trusted tunnel,
> and prefer short-lived tunnels for local experiments.

---

## Gate-level designs

Already synthesized? Load the structural Verilog netlist together with the
Liberty library that defines its standard cells, and navigate the gates the same
way as RTL:

> *"Load the Liberty library `pdk/stdcells.lib`, then the gate netlist
> `build/top.v`, and tell me what cells `top` is built from and what drives
> `data_out`."*

Hierarchy, per-cell counts (`get_module_card`), drivers/loads, and logic cones
all work on the netlist; cones stop at the sequential cells. A gate netlist
carries no source line info, so `get_source` applies to RTL only. A runnable
example lives in [`examples/`](examples/) (`stdcells.lib` + `counter2.v` +
`gate_level.py`).

---

## What you can ask

Once a design is loaded, your assistant can:

- **Resolve** any signal or instance by hierarchical path (with glob and
  did-you-mean suggestions).
- **Find** objects design-wide by pattern.
- **Show the hierarchy** of any module.
- **Get drivers / loads** of a net — the real endpoints, across hierarchy;
  literal drivers preserve four-state `0` / `1` / `X` / `Z` values.
- **Trace logic cones** (fan-in / fan-out) and see the register frontier.
- **Get source** — the exact SystemVerilog lines behind any object.
- **Get a module card** — ports, counts, clock/reset at a glance.
- **Recover design intent** — state-machine names, struct fields, parameter
  expressions lost during elaboration.

A runnable end-to-end walkthrough lives in [`examples/`](examples/), including
versions that run against [CVA6](https://github.com/openhwgroup/cva6) (a
production RISC-V core, cloned on demand — see
[`examples/cva6_demo.sh`](examples/cva6_demo.sh)) and
[CORE-V-MCU](https://github.com/openhwgroup/core-v-mcu) (a full multi-vendor
RISC-V SoC — see [`examples/core_v_mcu_demo.sh`](examples/core_v_mcu_demo.sh)).

---

## The Python escape hatch (off by default)

naja-scope also has a `query_python` tool that runs Python directly against the
loaded design, for queries the typed tools above cannot express. **It is not
registered unless you opt in:**

```bash
NAJA_SCOPE_ENABLE_PYTHON=1 naja-scope-mcp
```

It is unsandboxed `eval`/`exec` inside the server process — read-only by
convention, not enforced — so anything that can reach the server can run
arbitrary Python as the server's user. That matters most under `--transport
streamable-http`, where the server listens on a socket. Leave it off unless you
need it and trust every client that can reach the endpoint.

---

## Requirements

- Python 3.10+
- Works anywhere `najaeda` runs (Linux, macOS, Windows)

---

## Development

```sh
# from a checkout
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m pytest -q
```

The full test suite runs against a plain `pip install` of `najaeda` — no native
build required. The CVA6 cross-hierarchy cone regression
(`tests/test_zzz_cone_cva6.py`) is slow and skips automatically unless a CVA6
snapshot is present.

---

## Support & contact

- 🐛 **Found a bug or have a feature request?**
  [Open an issue on GitHub →](https://github.com/najaeda/naja-scope/issues)
- 📫 **Get in touch:** [contact@keplertech.io](mailto:contact@keplertech.io)

---

## License

Apache-2.0. See [LICENSE](LICENSE).
</content>
</invoke>
