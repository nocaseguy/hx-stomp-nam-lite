// frame_probe.asm - a wrapper around the Deluxe Comp's core (primitive 0x271a) that calls the stock
// process code, then looks for the DSP's outgoing SPI frames in memory and writes into their
// unused tail what it saw: the registers the stock code was called with and samples of the
// buffers they point to (a test image only).
//
// A frame is 256 words: FACEF00D first, D00FECAF last. Once per block it scans a slice
// of internal and external memory for the first word (and its halfword-swapped form),
// keeps the addresses whose word 255 is the matching last word, and writes into words
// 200..202 of each: 600DF00D, a tag, the call count. The M4's receive hook then shows
// whether those words arrive.

.equ MAGIC1,  0xFACEF00D
.equ MAGIC2,  0xF00DFACE
.equ TRAIL1,  0xD00FECAF
.equ TRAIL2,  0xECAFD00F
.equ PEYEN,   0x200000
.equ BDCST9,  0x400000
.equ SCAN_A,  0x80000                   // internal RAM, then the DDR2 the heaps use
.equ SCAN_B,  0x100000
.equ SCAN_C,  0x200000
.equ SCAN_D,  0x330000
.equ ORIG,    0x8d9c9                  // the stock process code of primitive 0x271a
.equ SLICE,   256                       // words looked at per call

.section dm 0xe4850
FP_SAVE:  .space 24
FP_CUR:   .space 1                      // the next address to look at (0: not started)
FP_CALLS: .space 1
FP_N:     .space 1                      // candidates
FP_LOG:   .space 16                     // what goes to words 200..215
FP_LIST:  .space 96                     // candidate addresses + 1

.section pm 0x0c4ef8
CUSTOM_AMP_ENTRY:
    DM(FP_LOG + 3) = I1;                // as called
    DM(FP_LOG + 4) = I2;
    DM(FP_LOG + 5) = I3;
    DM(FP_LOG + 6) = I0;
    DM(FP_SAVE + 0) = MODE1;
    BIT CLR MODE1 PEYEN | BDCST9;
    NOP;
    DM(FP_SAVE + 1) = R0;
    DM(FP_SAVE + 2) = R1;
    DM(FP_SAVE + 9) = I4;
    I4 = DM(FP_LOG + 3);                // the largest sample of each 16 words they point to, before
    CALL fp_max;
    DM(FP_LOG + 7) = R1;
    I4 = DM(FP_LOG + 4);
    CALL fp_max;
    DM(FP_LOG + 8) = R1;
    I4 = DM(FP_LOG + 5);
    CALL fp_max;
    DM(FP_LOG + 9) = R1;
    R0 = DM(FP_SAVE + 1);
    R1 = DM(FP_SAVE + 2);
    I4 = DM(FP_SAVE + 9);
    MODE1 = DM(FP_SAVE + 0);
    NOP;
    CALL ORIG;
    DM(FP_SAVE + 0) = MODE1;
    BIT CLR MODE1 PEYEN | BDCST9;
    NOP;
    DM(FP_SAVE + 1) = R0;
    DM(FP_SAVE + 2) = R1;
    DM(FP_SAVE + 3) = R2;
    DM(FP_SAVE + 4) = R3;
    DM(FP_SAVE + 5) = R4;
    DM(FP_SAVE + 6) = R5;
    DM(FP_SAVE + 7) = R6;
    DM(FP_SAVE + 8) = R7;
    DM(FP_SAVE + 9) = I4;
    DM(FP_SAVE + 10) = I5;
    DM(FP_SAVE + 11) = L4;
    DM(FP_SAVE + 12) = L5;
    DM(FP_SAVE + 15) = I6;
    DM(FP_SAVE + 16) = L6;
    L4 = 0; L5 = 0; L6 = 0;

    I4 = DM(FP_LOG + 3);                // and after
    CALL fp_max;
    DM(FP_LOG + 10) = R1;
    I4 = DM(FP_LOG + 4);
    CALL fp_max;
    DM(FP_LOG + 11) = R1;
    R0 = DM(0, I4);
    DM(FP_LOG + 13) = R0;
    I4 = DM(FP_LOG + 5);
    CALL fp_max;
    DM(FP_LOG + 12) = R1;
    R0 = DM(0, I4);
    DM(FP_LOG + 14) = R0;
    R0 = DM(1, I4);
    DM(FP_LOG + 15) = R0;

    R7 = DM(FP_CALLS);
    R7 = R7 + 1;
    DM(FP_CALLS) = R7;

    // ---- look at the next slice
    R1 = DM(FP_CUR);
    R1 = PASS R1;
    IF NE JUMP fp_have;
    R1 = SCAN_A;
fp_have:
    R2 = SCAN_D;
    COMP(R1, R2);
    IF GE JUMP fp_write;                // all looked at
    I4 = R1;
    I5 = FP_LIST;
    R0 = DM(FP_N);
    R6 = I5;
    R6 = R6 + R0;
    I5 = R6;                            // the end of the candidates so far
    R3 = MAGIC1;
    R4 = MAGIC2;
    LCNTR = SLICE, DO fp_scan UNTIL LCE;
      R5 = DM(I4, 1);
      R2 = I4;
      COMP(R5, R3);
      IF EQ DM(I5, 1) = R2;
      COMP(R5, R4);
fp_scan: IF EQ DM(I5, 1) = R2;
    R6 = I5;
    R2 = FP_LIST;
    R6 = R6 - R2;
    R2 = 90;                            // the list is full: stop adding
    COMP(R6, R2);
    IF LE JUMP fp_nf;
    R6 = 90;
fp_nf:
    DM(FP_N) = R6;
    R1 = I4;
    R2 = SCAN_B;
    COMP(R1, R2);
    IF NE JUMP fp_cstore;
    R1 = SCAN_C;                        // internal RAM done: on to the DDR2
fp_cstore:
    DM(FP_CUR) = R1;

    // ---- the test pattern into every candidate whose word 255 closes the frame
fp_write:
    R0 = DM(FP_N);
    R0 = PASS R0;
    IF EQ JUMP fp_out;
    I5 = FP_LIST;
    R5 = 0;                             // the candidate's number
    LCNTR = R0, DO fp_wr UNTIL LCE;
      R1 = DM(I5, 1);
      R1 = R1 - 1;
      I4 = R1;
      R2 = DM(I4, 0);
      R3 = MAGIC1;
      COMP(R2, R3);
      IF EQ JUMP fp_f1;
      R3 = MAGIC2;
      COMP(R2, R3);
      IF NE JUMP fp_skip;
      R3 = TRAIL2;
      R6 = 0xF00D600D;
      JUMP fp_chk;
fp_f1:
      R3 = TRAIL1;
      R6 = 0x600DF00D;
fp_chk:
      R2 = DM(255, I4);
      COMP(R2, R3);
      IF NE JUMP fp_skip;
      DM(200, I4) = R6;
      R2 = DM(FP_N);
      R2 = LSHIFT R2 BY 8;
      R2 = R2 OR R5;
      R3 = 0xC0DE0000;
      R2 = R2 OR R3;
      DM(201, I4) = R2;
      DM(202, I4) = R7;
      R2 = DM(FP_LOG + 3);
      DM(203, I4) = R2;
      R2 = DM(FP_LOG + 4);
      DM(204, I4) = R2;
      R2 = DM(FP_LOG + 5);
      DM(205, I4) = R2;
      R2 = DM(FP_LOG + 6);
      DM(206, I4) = R2;
      R2 = DM(FP_LOG + 7);
      DM(207, I4) = R2;
      R2 = DM(FP_LOG + 8);
      DM(208, I4) = R2;
      R2 = DM(FP_LOG + 9);
      DM(209, I4) = R2;
      R2 = DM(FP_LOG + 10);
      DM(210, I4) = R2;
      R2 = DM(FP_LOG + 11);
      DM(211, I4) = R2;
      R2 = DM(FP_LOG + 12);
      DM(212, I4) = R2;
      R2 = DM(FP_LOG + 13);
      DM(213, I4) = R2;
      R2 = DM(FP_LOG + 14);
      DM(214, I4) = R2;
      R2 = DM(FP_LOG + 15);
      DM(215, I4) = R2;
fp_skip:
fp_wr: R5 = R5 + 1;

fp_out:
    R0 = DM(FP_SAVE + 1);
    R1 = DM(FP_SAVE + 2);
    R2 = DM(FP_SAVE + 3);
    R3 = DM(FP_SAVE + 4);
    R4 = DM(FP_SAVE + 5);
    R5 = DM(FP_SAVE + 6);
    R6 = DM(FP_SAVE + 7);
    R7 = DM(FP_SAVE + 8);
    I4 = DM(FP_SAVE + 9);
    I5 = DM(FP_SAVE + 10);
    L4 = DM(FP_SAVE + 11);
    L5 = DM(FP_SAVE + 12);
    I6 = DM(FP_SAVE + 15);
    L6 = DM(FP_SAVE + 16);
    MODE1 = DM(FP_SAVE + 0);
    NOP;
    RTS (LR);

fp_max:                                 // R1 = the largest |sample| of the 16 words at I4
    R1 = 0;
    LCNTR = 16, DO fp_mx UNTIL LCE;
      F0 = DM(I4, 1);
      F0 = ABS F0;
fp_mx: F1 = MAX(F0, F1);
    RTS;
