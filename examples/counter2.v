// counter2.v — a gate-level (structural) 2-bit free-running counter.
//
// This is what a netlist looks like AFTER synthesis: no always blocks, no
// operators — just standard-cell instances (from stdcells.lib) wired together.
// naja-scope navigates this exactly like an elaborated SystemVerilog design:
// resolve cell instances, trace what drives each flop, walk logic cones.
//
//   bit 0 toggles every clock:      q0 <= ~q0
//   bit 1 toggles when q0 is high:   q1 <= q1 ^ q0
//
// Load order: load_liberty(["stdcells.lib"]) then load_verilog(["counter2.v"]).

module counter2 (
  input  clk,
  output q0,
  output q1
);
  wire n0;   // ~q0
  wire x1;   // q1 ^ q0

  // bit 0: toggle flip-flop
  INV  u_inv0 (.I(q0),  .Z(n0));
  DFF  u_ff0  (.CK(clk), .D(n0), .Q(q0));

  // bit 1: flips on q0
  XOR2 u_xor1 (.A(q1),  .B(q0), .Z(x1));
  DFF  u_ff1  (.CK(clk), .D(x1), .Q(q1));
endmodule
