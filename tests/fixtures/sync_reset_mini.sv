// Miniature module with a synchronous reset (no reset in the sensitivity
// list): exercises SNLDesign.getSyncResetTerms()/getSyncSetTerms() and the
// SyncReset/SyncSet SNLTermRole values (najaeda 0.7.12), as opposed to
// uart.sv's async-reset flops.
module sync_reset_mini (
    input  logic clk,
    input  logic rst,
    input  logic [7:0] d,
    output logic [7:0] q
);
  always_ff @(posedge clk) begin
    if (rst) q <= '0;
    else     q <= d;
  end
endmodule
