# Example: a guided tour on a small UART

This folder contains a tiny, self-contained SystemVerilog design
([`uart.sv`](uart.sv)) and a scripted tour ([`walkthrough.py`](walkthrough.py))
that asks naja-scope the kind of questions an AI agent asks — and shows the
small, exact answers it gets back.

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
