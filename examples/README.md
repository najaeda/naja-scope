# Examples: guided tours

This folder contains tiny, self-contained designs and scripted tours that ask
naja-scope the kind of questions an AI agent asks — and show the small, exact
answers it gets back:

- **RTL** — [`uart.sv`](uart.sv) + [`walkthrough.py`](walkthrough.py): a small
  SystemVerilog UART transmitter.
- **Gate-level** — [`stdcells.lib`](stdcells.lib) + [`counter2.v`](counter2.v) +
  [`gate_level.py`](gate_level.py): a post-synthesis structural netlist driven
  by a Liberty cell library (see [below](#gate-level-a-synthesized-netlist)).
- **CVA6** — [`cva6_demo.sh`](cva6_demo.sh) + [`cva6_demo.py`](cva6_demo.py): the
  same tour against [CVA6](https://github.com/openhwgroup/cva6), a production
  RISC-V core, cloned on demand (see [below](#cva6-a-real-production-core)).

## RTL tour

The UART tour ([`walkthrough.py`](walkthrough.py)) loads
[`uart.sv`](uart.sv) and asks a handful of real design questions.

## Run it

From a checkout (after `pip install -e .` or `pip install naja-scope`):

```sh
python examples/walkthrough.py
```

The same answers are pinned by
[`tests/test_examples_walkthrough.py`](../tests/test_examples_walkthrough.py),
which loads this exact `uart.sv` — so this tour can't drift from how the tools
actually behave.

## The design

`uart.sv` is a small UART transmitter: a top module `uart_top` instantiating
`uart_tx`, which contains a 4-state FSM, a shift register, two `counter`
instances (different parameterizations), and a registered serial output `tx_o`.

## What the tour shows

**1. Load once, then ask many questions.**

```
loaded: top=uart_top  direct children=1  ports=6
```

**2. "What's the top-level hierarchy?"** → `get_hierarchy`

```
- uart_top  [uart_top]  (examples/uart.sv:98-109)
  - u_tx  [uart_tx]  (examples/uart.sv:106-108)
```

**3. "What drives the registered output `tx_o`?"** → `get_drivers`

```
driver model : naja_dff  (sequential=True)
output pin   : Q
source       : examples/uart.sv:93-94
```

No guessing across hierarchy — the actual flop that drives the port, with its
exact source line.

**4. "Show me the RTL behind that flop."** → `get_source`

```systemverilog
always_ff @(posedge clk or negedge rst_n) begin
  if (!rst_n) tx_o <= 1'b1;
  else        tx_o <= tx_next;
end
```

**5. "What feeds the FSM next-state logic?"** → `trace_cone` (fan-in)

```
nodes in cone     : 70
by kind           : {'internal': 60, 'flop': 6, 'root': 2, 'ports': 2}
register frontier : 3 flop(s)
black boxes       : 0   (cone fully traversed the combinational logic)
```

Each question is three to four small calls — no source dump, no scrolling
through files, and the agent's context stays tiny.

## Using it from your AI assistant

Instead of running the script, point your MCP client at the server and ask in
natural language:

> *"Load `examples/uart.sv` with top `uart_top`, then tell me what drives
> `tx_o` and show me the RTL behind it."*

See the [top-level README](../README.md) for client setup
(`claude mcp add naja-scope -- naja-scope-mcp`).

## Gate-level: a synthesized netlist

naja-scope is not only for RTL. Point it at a **structural Verilog netlist**
plus the **Liberty library** that defines its standard cells, and you navigate
the gates the same way.

[`counter2.v`](counter2.v) is a 2-bit counter built entirely from cells
(`INV`, `XOR2`, `DFF`) defined in [`stdcells.lib`](stdcells.lib) — what a design
looks like *after* synthesis: no `always` blocks, no operators, just wired-up
instances.

```sh
python examples/gate_level.py
```

The tour loads the library first, then the netlist, and shows:

```
loaded: top=counter2  cells=4  ports=3
cells : {'DFF': 2, 'INV': 1, 'XOR2': 1}        # get_module_card
q1 driven by: counter2.u_ff1  model=DFF pin=Q  # get_drivers
fan-in of u_ff1.D stops at cells: u_ff0, u_ff1 # trace_cone
```

Two calls to load (`load_liberty`, then `load_verilog`), then the same
`get_hierarchy` / `get_module_card` / `get_drivers` / `trace_cone` tools as on
RTL. The flops are opaque library cells, so a fan-in cone stops at them as its
cell (black-box) frontier. A gate netlist carries no SystemVerilog source info,
so `get_source` has nothing to point at here — gate-level is about structure and
connectivity. [`tests/test_examples_gate_level.py`](../tests/test_examples_gate_level.py)
pins these answers.

From your AI assistant, in natural language:

> *"Load the Liberty library `examples/stdcells.lib`, then the gate netlist
> `examples/counter2.v`, and tell me what cells it's built from and what drives
> `q1`."*

## CVA6: a real production core

`uart.sv` and `counter2.v` are tiny on purpose — easy to read end to end. To
see naja-scope on something that actually needs it, [`cva6_demo.py`](cva6_demo.py)
runs the same kind of tour against [CVA6](https://github.com/openhwgroup/cva6),
a production RISC-V core: ~4800 direct children under the top module once
elaborated, ten real pipeline-stage submodules buried under thousands of
`assign`-glue instances.

CVA6 is a large third-party repo, so it isn't checked into this repo. Instead
[`cva6_demo.sh`](cva6_demo.sh) clones it at a pinned tag (only the submodules
the elaborated config needs — not the full corev_apu/verif/docs submodule
set) and runs the tour:

```sh
./examples/cva6_demo.sh
```

Or point it at a CVA6 checkout you already have:

```sh
CVA6_REPO_DIR=~/WORK/cva6 ./examples/cva6_demo.sh
```

It shows:

- **Hierarchy that filters glue, not dumps it** — `get_hierarchy` reports
  ~4800 `assign` instances as a count and surfaces the 10 real submodules
  (frontend, id_stage, issue_stage, ex_stage, commit_stage, csr_regfile,
  perf_counters, controller, the cache subsystem, rvfi probes) in one bounded
  call.
- **A driver, three hierarchy levels deep** — `get_drivers` on the serial
  divider's FSM state register resolves straight to the flip-flop and its
  `serdiv.sv` source line, no scrolling through the multiplier/divider unit.
- **A cross-hierarchy fan-in cone** — `trace_cone` on the divider's
  next-state logic shows its register frontier reaching *outside* the EX
  stage entirely, into `csr_regfile_i` (the privilege-level register gates
  the divider) — a fact no textual grep of `serdiv.sv` could ever reveal.

This is the same tour that runs in CI as a regression
(`.github/workflows/cva6-demo.yml`) — MCP-only, no agent, so it's
deterministic and free to run. To see an actual *agent* driving the same MCP
server, run [`cva6_demo_agent.sh`](cva6_demo_agent.sh) instead (defaults to
Claude Code; pluggable via `AGENT_CMD`) — that one is never run in CI.
