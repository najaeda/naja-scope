// Miniature of the cva6-privlvl-enum gate for intent-layer tests: a PACKAGE
// typedef enum + a packed struct typedef (members/fields in the package, not at
// the register), plus symbolic localparams (a ternary and a $clog2).
package mini_pkg;
  typedef enum logic [1:0] {
    ST_IDLE = 2'b00,
    ST_RUN  = 2'b01,
    ST_DONE = 2'b11
  } state_e;
  typedef struct packed {
    logic        valid;
    logic [3:0]  id;
  } req_t;
  localparam int PLEN = (32 == 32) ? 34 : 56;
endpackage

module intent_mini #(
    parameter int DEPTH = 4
) (
    input  logic clk,
    input  logic rst_n
);
  import mini_pkg::*;
  localparam int IDX_W = $clog2(DEPTH);

  mini_pkg::state_e state_q;
  req_t             req_q;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state_q <= ST_IDLE;
      req_q   <= '0;
    end else begin
      state_q <= ST_RUN;
      req_q   <= '{valid: 1'b1, id: 4'h5};
    end
  end
endmodule
