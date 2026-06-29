# naja-scope

[![PyPI version](https://img.shields.io/pypi/v/naja-scope.svg)](https://pypi.org/project/naja-scope/)
[![Python versions](https://img.shields.io/pypi/pyversions/naja-scope.svg)](https://pypi.org/project/naja-scope/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/najaeda/naja-scope/blob/main/LICENSE)

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

All responses are token-bounded: lists paginate, large results truncate with
clear markers. Your context stays small; your answers stay accurate.

---

## Does it actually help?

We ran a head-to-head on [CVA6](https://github.com/openhwgroup/cva6) (a
production RISC-V core): the same 17 design questions, answered by Claude once
with **only naja-scope** and once with **only `grep`/file reading** over the
source tree.

| Approach            | Correct answers | Conversation turns | Input tokens |
| ------------------- | :-------------: | :----------------: | :----------: |
| **naja-scope**      |    **17 / 17**  |       **77**       |   **182 k**  |
| grep + read source  |     10 / 17     |         123        |     888 k    |

More correct answers, fewer back-and-forth turns, and **~5× fewer tokens** — the
agent stops scrolling through files and goes straight to the structural answer.

---

## Install

```sh
pip install naja-scope
```

That's it — `najaeda` and the MCP runtime come along automatically.

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

## What you can ask

Once a design is loaded, your assistant can:

- **Resolve** any signal or instance by hierarchical path (with glob and
  did-you-mean suggestions).
- **Find** objects design-wide by pattern.
- **Show the hierarchy** of any module.
- **Get drivers / loads** of a net — the real endpoints, across hierarchy.
- **Trace logic cones** (fan-in / fan-out) and see the register frontier.
- **Get source** — the exact SystemVerilog lines behind any object.
- **Get a module card** — ports, counts, clock/reset at a glance.
- **Recover design intent** — state-machine names, struct fields, parameter
  expressions lost during elaboration.

---

## Requirements

- Python 3.10+
- Works anywhere `najaeda` runs (Linux, macOS)

---

## Support & contact

- 🐛 **Found a bug or have a feature request?**
  [Open an issue on GitHub →](https://github.com/najaeda/naja-scope/issues)
- 📫 **Get in touch:** [contact@keplertech.io](mailto:contact@keplertech.io)

---

## License

Apache-2.0. See [LICENSE](https://github.com/najaeda/naja-scope/blob/main/LICENSE).
