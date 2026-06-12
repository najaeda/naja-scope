// Small UART-class fixture: hierarchy, buses, FSM, two parameterizations of
// the same module (exercises uniquification), registered output.
//
// Style note: najaeda's SV lowering (0.5.2 beta) supports simple
// `if (!rst) ... else ...` always_ff patterns; complex branch chains live in
// always_comb next-state logic instead.

module counter #(parameter W = 4) (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         en,
    input  logic         clr,
    output logic [W-1:0] count
);
  logic [W-1:0] count_n;

  always_comb begin
    count_n = count;
    if (clr)     count_n = '0;
    else if (en) count_n = count + 1'b1;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) count <= '0;
    else        count <= count_n;
  end
endmodule

module uart_tx #(parameter DIV_W = 4) (
    input  logic       clk,
    input  logic       rst_n,
    input  logic       tx_start,
    input  logic [7:0] tx_data,
    output logic       tx_o,
    output logic       tx_busy
);
  localparam logic [1:0] IDLE = 2'd0, START = 2'd1, DATA = 2'd2, STOP = 2'd3;

  logic [1:0]       state, state_n;
  logic [7:0]       shift_q, shift_n;
  logic [2:0]       bit_idx;
  logic [DIV_W-1:0] div_cnt;
  logic             baud_tick, bit_done, clr_cnt;
  logic             tx_next;

  counter #(.W(DIV_W)) u_div_cnt (
      .clk(clk), .rst_n(rst_n), .en(tx_busy), .clr(clr_cnt), .count(div_cnt));
  counter #(.W(3)) u_bit_cnt (
      .clk(clk), .rst_n(rst_n), .en(baud_tick), .clr(clr_cnt),
      .count(bit_idx));

  assign baud_tick = (div_cnt == {DIV_W{1'b1}});
  assign bit_done  = baud_tick && (bit_idx == 3'd7);
  assign clr_cnt   = (state == IDLE);
  assign tx_busy   = (state != IDLE);

  always_comb begin
    state_n = state;
    case (state)
      IDLE:    if (tx_start) state_n = START;
      START:   if (baud_tick) state_n = DATA;
      DATA:    if (bit_done) state_n = STOP;
      STOP:    if (baud_tick) state_n = IDLE;
      default: state_n = IDLE;
    endcase
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) state <= IDLE;
    else        state <= state_n;
  end

  always_comb begin
    shift_n = shift_q;
    if (tx_start)       shift_n = tx_data;
    else if (baud_tick) shift_n = {1'b1, shift_q[7:1]};
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) shift_q <= '0;
    else        shift_q <= shift_n;
  end

  always_comb begin
    case (state)
      START:   tx_next = 1'b0;
      DATA:    tx_next = shift_q[0];
      default: tx_next = 1'b1;
    endcase
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) tx_o <= 1'b1;
    else        tx_o <= tx_next;
  end
endmodule

module uart_top (
    input  logic       clk,
    input  logic       rst_n,
    input  logic       tx_start,
    input  logic [7:0] tx_data,
    output logic       tx_o,
    output logic       tx_busy
);
  uart_tx #(.DIV_W(4)) u_tx (
      .clk(clk), .rst_n(rst_n), .tx_start(tx_start), .tx_data(tx_data),
      .tx_o(tx_o), .tx_busy(tx_busy));
endmodule
