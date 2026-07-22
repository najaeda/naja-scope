module net_types (
  output logic unknown_o,
  output logic high_z_o,
  output logic zero_o,
  output logic one_o,
  output logic [3:0] mixed_o
);
  assign unknown_o = 1'bx;
  assign high_z_o  = 1'bz;
  assign zero_o    = 1'b0;
  assign one_o     = 1'b1;
  assign mixed_o   = 4'bxz01;
endmodule
