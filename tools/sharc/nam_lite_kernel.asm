// nam_lite_kernel.asm - NAM A2 Lite (3 channels) as a primitive of the stock
// HX Stomp 3.80 firmware: hooked as 0x9c75 by tools/patch_amp.py, called by
// the stock dispatcher once per block of 16 samples with I1 = input and I2 =
// output. The model data
// (header, layer table, weights, the list of memory to clear) is not here:
// tools/sharc/nam_lite.py adds it from a .nam file and writes the file
// patch_amp.py assembles.
//
// A layer at a time over the block, two samples at a time: in SIMD mode PEx
// works on sample t and PEy on t + 1. A layer keeps its input as three rings,
// one per channel, so x(t) and x(t + 1) are neighbours: a load gives each
// element its sample, and each weight is broadcast to both (BDCST9, through
// I9). An input pair, once loaded, is used by all three output channels.
// Every sum is added in nam_a2.asm's order (bias, mix-in, then the taps
// oldest first, channel by channel), so the output is nam_a2.asm's bit for
// bit (tools/sharc/nam_lite.py --check).
//
// A ring of length L = (K-1)d + 16 holds exactly what a block needs. The
// element PEy reads one word past PEx's, so after the last word of a ring
// comes a guard word, a copy of its first. Rings in DDR2 (the long layers
// that do not fit inside) are copied, a block's taps at a time, into SCR
// first: no paired access goes outside.
//
// Memory: Block 3 0xe4842..0xe7fff (free in 3.80) for the state, the model
// table and the rings that fit; the layer weights after this code in Block 2
// (to 0xc7fff) when they fit, where the ring reads of the same instructions
// are not; DDR2 from 0x324500 (after Heap 6 as patch_amp moves it) for the
// other rings. The rings are filled with the model's silence state on the first call
// (N_INIT, 0 at boot) and after a load.
// One instance at a time has this memory: see n_own.
//
// Knobs: Drive in DM(5, I0), Ch Vol in DM(6, I0), Model in DM(7, I0) (an integer:
// User IR slot 1 .. 128, silence when that holds no NAM; 0 the built-in model), Bass, Mid, Treble and
// Presence in DM(8..11, I0) (a tone stack after the model, flat at 5.0, -12
// .. +12 dB: 100 Hz low shelf, 650 Hz peak, 2.5 and 5.5 kHz high shelves),
// 0..1 (the model's blob
// routes them there; DM(3) and DM(4) belong to fn_ctrl 0x611ddd): Drive the
// input gain, 0 dB at 5.0 (the capture's level), -20 .. +20 dB, 4 dB a unit; Ch Vol the
// output level 4 k^2 (0 mute, 0 dB at 5.0, +12 dB at 10.0).
//
// It sets CBUFEN for its circular buffers: on the unit, rings that did not wrap
// put a tone at each ring's rate into the output (92, 217, 475 Hz: rings of
// 521, 221, 101 words). Every register it changes is put back, MODE1 too, except I1 and I2 (the
// dispatcher loads them for each call). I6/I7, I12-I15, M5-M7 and M12-M15
// are not touched. Hardware loops nest three deep.

.equ PEYEN,    0x200000
.equ BDCST9,   0x400000
.equ CBUFEN,   0x1000000

.equ N_SAVE,   0xe4850          // 64 words
.equ N_INIT,   0xe4890          // 0 until the rings have been cleared
.equ N_LEVEL,  0xe4891
.equ N_OWNER,  0xe4892          // I0 of the instance that has this memory (0 at boot)
.equ N_TICK,   0xe4893          // counted up by the owner, each call
.equ N_T0,     0xe4894          // EMUCLK at entry (nam_lite.py --meter)
.equ N_MCNT,   0xe4895          // --meter: blocks so far
.equ N_SIG,    0xe4896          // the loaded model: its top address + its first 16 words
.equ N_GAIN,   0xe4897          // the model's fade-in step 0 .. 16 at the start of a block
.equ N_G1,     0xe4898          // and at its end (gain FADE_TAB[step], in a line between)
.equ N_MG,     0xe4899          // the tail's fade-out step 17 .. 0 at the start of a block
.equ N_MR,     0xe489a          // where the tail reads in HIST (going back)
.equ N_HW,     0xe489b          // where the block's output goes in HIST
                                // A model change crossfades with no gap: the new model, from
                                // cleared rings, fades in over 16 blocks (5.3 ms) while the
                                // last output, played backwards from HIST, fades out (sin and
                                // cos: equal power). The tail starts on the last sample heard,
                                // so there is no step. (Keeping the rings for the new model is
                                // worse: its weights on the old one's activations burst.)
.equ HIST,     0x327500         // DDR2: the last 512 outputs before the tone stack
.equ FADE_TAB, 0x327480         // DDR2: sin(pi/2 k/16), k = 0 .. 16, then 1.0 (k = 17)
.equ EQ_C,     0xe7fe0          // the tone stack: 4 bands x {b0, b1, b2, -a1, -a2}
.equ EQ_S,     0xe7ff4          // its state, 4 x {s1, s2} (0 at boot, never cleared)
.equ EQ_IDX,   0xe7ffc          // each band's knob step 0..100 now (-1 at boot: load)
.equ EQ_TAB,   0x326a00         // DDR2: 4 bands x 101 steps x 5 coefficients (nam_lite.py)
.equ DRIVE_TAB, 0x327400        // DDR2: Drive's input gain for each step 0.0 .. 10.0 (-20 .. +20 dB)
.equ IR_FLAG,  0x2ab56e         // the stock User IR slots: slot s loaded,
.equ IR_TOP,   0x2abded         // and its sample k at IR_TOP + s * 0x800 - k
.equ P_SEEN,   100              // in each instance's own block (I0; zeroed by fn_reset
.equ P_MET,    101              // 0x611e90): N_TICK at its last call, and 1 once it was called
.equ IN,       0xe48a0          // the block's input, gained (16)
.equ X,        0xe48b0          // the signal between layers, [channel][16]
.equ HS,       0xe48e0          // sum of activations, the head's input, [channel][16]
.equ SCR,      0xe4910          // a DDR2 layer's taps, [channel][tap][16] (3 x 6 x 16)
.equ MODEL,    0xe4a30          // header and layer table: nam_lite.py

.equ H_LAYERS, 0                // header
.equ H_TABLE,  1
.equ H_RECH,   2                // three rechannel weights (DM)
.equ H_HEAD,   3                // head bias, then 16 x 3 weights, oldest tap first (PM)
.equ H_SCALE,  4
.equ H_HB0,    5                // the head's three rings (L 31, a guard after each)
.equ H_HB1,    6
.equ H_HB2,    7
.equ H_HW,     8                // their write offset
.equ H_LMAP,   9                // where a model's 1,943 words go: count, then (address, length)
.equ H_BUILTIN, 10              // the built-in model, laid out as an IR slot (its top word)
.equ H_CLR,    11               // the rings: count, then (address, length, silence value / 16) (in DDR2,
                                // as H_LMAP's list: both are read only on a load or a clear)

.equ T_B0,     0                // layer table: channel 0's ring; channel j's at T_B0 + j T_STRIDE
.equ T_STRIDE, 1                // (L + 1 inside, for the guard word; L in DDR2)
.equ T_L,      2                // ring length (K-1)d + 16
.equ T_W,      3                // where this block goes in the rings
.equ T_K,      4
.equ T_S,      5                // tap stride as read: d, or 16 in SCR. To the next pair, after
                                // a step of T_KS: 2 - 2s for I0, 2 - s for I1, I2 (each step
                                // shorter than the ring: the chip puts an index back into its
                                // buffer once only)
.equ T_WT,     6                // weights (PM)
.equ T_KD,     7                // -(K-1)d: the oldest tap from the newest
.equ T_DDR,    8                // 0, or 1 for rings in DDR2 (read through SCR)
.equ T_DM16,   9                // d - 16: one tap's 16 to the next
.equ T_KS,     10               // -(K-1)s
.equ T_SIZE,   11

.section pm 0x0c4ef8

CUSTOM_AMP_ENTRY:
    DM(N_SAVE + 0) = MODE1;
    // METER ENTRY (nam_lite.py --meter puts code here)
    BIT CLR MODE1 PEYEN | BDCST9;       // (stock kernels leave them off; be sure)
    BIT SET MODE1 CBUFEN;               // the rings wrap: circular buffers on (MODE1 is put back)
    DM(N_SAVE + 1) = R0;
    DM(N_SAVE + 2) = R1;
    DM(N_SAVE + 3) = R2;
    DM(N_SAVE + 4) = R3;
    DM(N_SAVE + 5) = R4;
    DM(N_SAVE + 6) = R5;
    DM(N_SAVE + 7) = R6;
    DM(N_SAVE + 8) = R7;
    DM(N_SAVE + 9) = R8;
    DM(N_SAVE + 10) = R9;
    DM(N_SAVE + 11) = R10;
    DM(N_SAVE + 12) = R11;
    DM(N_SAVE + 13) = R12;
    DM(N_SAVE + 14) = R13;
    DM(N_SAVE + 15) = R14;
    DM(N_SAVE + 16) = R15;
    DM(N_SAVE + 17) = S0;
    DM(N_SAVE + 18) = S1;
    DM(N_SAVE + 19) = S2;
    DM(N_SAVE + 20) = S3;
    DM(N_SAVE + 21) = S4;
    DM(N_SAVE + 22) = S5;
    DM(N_SAVE + 23) = S8;
    DM(N_SAVE + 24) = S9;
    DM(N_SAVE + 25) = S10;
    DM(N_SAVE + 26) = S11;
    DM(N_SAVE + 27) = S12;
    DM(N_SAVE + 28) = S13;
    DM(N_SAVE + 29) = S14;
    DM(N_SAVE + 30) = B0;
    DM(N_SAVE + 31) = I0;
    DM(N_SAVE + 32) = B1;
    DM(N_SAVE + 33) = B2;
    DM(N_SAVE + 34) = B3;
    DM(N_SAVE + 35) = I3;
    DM(N_SAVE + 36) = B4;
    DM(N_SAVE + 37) = I4;
    DM(N_SAVE + 38) = B5;
    DM(N_SAVE + 39) = I5;
    DM(N_SAVE + 40) = M0;
    DM(N_SAVE + 41) = M1;
    DM(N_SAVE + 42) = M2;
    DM(N_SAVE + 43) = M3;
    DM(N_SAVE + 44) = M4;
    DM(N_SAVE + 45) = B8;
    DM(N_SAVE + 46) = I8;
    DM(N_SAVE + 47) = B9;
    DM(N_SAVE + 48) = I9;
    DM(N_SAVE + 49) = B10;
    DM(N_SAVE + 50) = I10;
    DM(N_SAVE + 51) = B11;
    DM(N_SAVE + 52) = I11;
    DM(N_SAVE + 53) = M8;
    DM(N_SAVE + 54) = M9;
    DM(N_SAVE + 55) = M10;
    DM(N_SAVE + 56) = M11;

    // ---- one instance runs the model, others pass their input through. The
    // owner counts N_TICK up; another instance that finds it unchanged since
    // its own last call takes over (the owner is gone) and clears the rings.
    L1 = 0;
    L2 = 0;
    R0 = I0;
    R1 = DM(N_OWNER);
    COMP(R0, R1);
    IF EQ JUMP n_mine;
    R2 = DM(N_TICK);
    R3 = DM(P_SEEN, I0);
    DM(P_SEEN, I0) = R2;
    R4 = DM(P_MET, I0);
    DM(P_MET, I0) = R0;                 // (I0: not 0)
    COMP(R2, R3);
    IF NE JUMP n_pass;
    R4 = PASS R4;
    IF EQ JUMP n_pass;
    DM(N_OWNER) = R0;                   // take over
    R0 = 0;
    DM(N_INIT) = R0;
    DM(N_GAIN) = R0;                    // and fade in (no tail: that instance is gone)
    DM(N_MG) = R0;
n_mine:
    R0 = DM(N_TICK);
    R0 = R0 + 1;
    DM(N_TICK) = R0;
    JUMP n_own;
n_pass:
    LCNTR = 16, DO n_passw UNTIL LCE;
      R0 = DM(I1, 1);
n_passw: DM(I2, 1) = R0;
    JUMP n_back;

n_own:

    F0 = DM(5, I0);                     // the knobs (I0 is the dispatcher's parameter block):
    F1 = 100.0;                         // Drive, the input gain, from DRIVE_TAB by its step
    F0 = F0 * F1;
    F1 = 0.5;
    F0 = F0 + F1;
    R0 = TRUNC F0;
    R1 = 0;
    R0 = MAX(R0, R1);
    R1 = 100;
    R0 = MIN(R0, R1);
    R1 = DRIVE_TAB;
    R0 = R0 + R1;
    I3 = R0;
    F14 = DM(0, I3);
    F0 = DM(6, I0);
    F0 = F0 * F0;
    F1 = 4.0;
    F0 = F0 * F1;
    DM(N_LEVEL) = F0;                   // output level, 4 k^2
    B10 = I1;                           // the block's input and output, through PM
    B11 = I2;
    L0 = 0; L3 = 0; L4 = 0; L5 = 0;     // (L1, L2 are 0 already)
    L8 = 0; L9 = 0; L10 = 0; L11 = 0;
    M9 = 1; M10 = 2;

    // ---- the model: Model (DM(7, I0)), the User IR list as the IR block's IR Select,
    // an integer 1 .. 128: that User IR slot when it holds a NAM Lite model
    // (tools/nam2ir.py: its first words 0.5, -0.5, 3.0, scale, 1871 / 1024; the
    // -0.5 is not checked), else
    // (a cab IR, an empty slot) silence. 0 (a model with no Model parameter,
    // whose DM(7) fn_reset left 0) is the built-in one. A
    // float (an older blob) is truncated. A change, or new contents, loads it at once: that
    // block has only the tail (N_MG), the next clears the rings and the model fades in.
    R8 = DM(MODEL + H_BUILTIN);
    R0 = DM(7, I0);
    R1 = 0x800000;
    COMP(R0, R1);
    IF LT JUMP n_int;                    // an integer (a float >= 2^-126 is not)
    R0 = TRUNC F0;
n_int:
    R1 = 1;
    R0 = R0 - R1;
    IF LT JUMP n_pick;                   // 0: the built-in model
    R1 = 128;
    COMP(R0, R1);
    IF GE JUMP n_none;
    R1 = IR_FLAG;
    R1 = R1 + R0;
    I3 = R1;
    R1 = DM(0, I3);
    R1 = PASS R1;
    IF EQ JUMP n_none;                   // an empty slot
    R1 = LSHIFT R0 BY 11;
    R2 = IR_TOP;
    R1 = R1 + R2;
    I3 = R1;
    F2 = DM(0, I3);
    F3 = 0.5;
    COMP(F2, F3);
    IF NE JUMP n_none;
    F2 = DM(-2, I3);
    F3 = 3.0;
    COMP(F2, F3);
    IF NE JUMP n_none;
    F2 = DM(-4, I3);
    F3 = 1.8271484375;                  // 1871 / 1024 (HX Edit refuses samples beyond +-15.8)
    COMP(F2, F3);
    IF NE JUMP n_none;
    R8 = R1;                            // a NAM Lite model
n_pick:
    I3 = R8;
    R5 = R8;
    LCNTR = 16, DO n_sigw UNTIL LCE;
      R6 = DM(I3, -1);
n_sigw: R5 = R5 + R6;
    R6 = DM(N_SIG);
    COMP(R5, R6);
    IF EQ JUMP n_same;
    DM(N_SIG) = R5;                     // another model: crossfade to it, and load it
    CALL n_cut;
    JUMP n_load;
n_same:
    R0 = DM(N_GAIN);                    // the same model: fade in, or stay at 16
    R0 = R0 + 1;
    R1 = 16;
    R0 = MIN(R0, R1);
    DM(N_G1) = R0;
    JUMP n_have;
n_none:
    R0 = DM(N_SIG);                     // no model in that slot: silence (after the tail)
    R0 = PASS R0;
    IF EQ JUMP n_zero;
    CALL n_cut;                         // (R0 = 0 after it)
    DM(N_SIG) = R0;                     // none loaded: a model in the slot loads, from
    JUMP n_zero;                        // cleared rings
n_load:                                 // load it: each word x the scale, through the map
    I3 = R8;
    F3 = DM(-3, I3);
    MODIFY(I3, -8);
    I4 = DM(MODEL + H_LMAP);
    R2 = DM(0, I4);
    MODIFY(I4, 1);
    LCNTR = R2, DO n_ldr UNTIL LCE;
      I5 = DM(0, I4);
      R1 = DM(1, I4);
      LCNTR = R1, DO n_ldw UNTIL LCE;
        F0 = DM(I3, -1);
        F0 = F0 * F3;
n_ldw:  DM(I5, 1) = F0;
n_ldr: MODIFY(I4, 2);
n_zero:                                 // no model this block: the tail alone
    R0 = 0;
    DM(N_INIT) = R0;
    DM(N_G1) = R0;
    I11 = B11;
    LCNTR = 16, DO n_ldz UNTIL LCE;
n_ldz: PM(I11, M9) = R0;
    JUMP n_mix;
n_have:
    // ---- the tone knobs, Bass, Mid, Treble, Presence (DM(8..11, I0)): each
    // step 0.0 .. 10.0 has its five coefficients in EQ_TAB, copied when it moves
    I3 = I0;
    MODIFY(I3, 8);
    I4 = EQ_IDX;
    I5 = EQ_C;
    R9 = EQ_TAB;
    LCNTR = 4, DO n_eqk UNTIL LCE;
      F0 = DM(I3, 1);
      F1 = 100.0;
      F0 = F0 * F1;
      F1 = 0.5;
      F0 = F0 + F1;
      R0 = TRUNC F0;
      R1 = 0;
      R0 = MAX(R0, R1);
      R1 = 100;
      R0 = MIN(R0, R1);
      R1 = DM(0, I4);
      COMP(R0, R1);
      IF EQ JUMP n_eqs;
      DM(0, I4) = R0;
      R1 = R0 + R0;                     // 5 x step
      R1 = R1 + R1;
      R1 = R1 + R0;
      R1 = R1 + R9;
      I0 = R1;                          // (I0 is free: the knobs are read)
      I2 = I5;                          // (I1, I2 are free: B10, B11 hold the block's input, output)
      LCNTR = 5, DO n_eqw UNTIL LCE;
        R1 = DM(I0, 1);
n_eqw:  DM(I2, 1) = R1;
n_eqs:
      MODIFY(I4, 1);
      MODIFY(I5, 5);
      R1 = 505;                         // 101 steps x 5: the next band's table
      R9 = R9 + R1;
      NOP;
n_eqk: NOP;

    R0 = DM(N_INIT);                    // first call: every ring and guard to the model's
    R0 = PASS R0;                       // silence state (a constant per ring)
    IF NE JUMP n_go;
    I4 = DM(MODEL + H_CLR);
    R2 = DM(0, I4);
    MODIFY(I4, 1);
    F5 = 16.0;                          // (the values are kept / 16: HX Edit's +-15.8)
    LCNTR = R2, DO n_clr UNTIL LCE;
      I3 = DM(0, I4);
      R1 = DM(1, I4);
      F0 = DM(2, I4);
      F0 = F0 * F5;
      LCNTR = R1, DO n_clrw UNTIL LCE;
n_clrw: DM(I3, 1) = R0;
      NOP;
n_clr: MODIFY(I4, 3);
    R0 = 1;
    DM(N_INIT) = R0;

n_go:
    I3 = X;                             // x = rechannel * in, hs = 0
    I5 = HS;
    I0 = IN;
    I4 = DM(MODEL + H_RECH);
    F1 = DM(0, I4);
    F2 = DM(1, I4);
    F3 = DM(2, I4);
    R12 = 0;
    LCNTR = 16, DO n_in UNTIL LCE;
      F15 = PM(I10, M9);
      F15 = F15 * F14;
      DM(I0, 1) = F15;
      F8 = F1 * F15;
      DM(0, I3) = F8;
      F8 = F2 * F15;
      DM(16, I3) = F8;
      F8 = F3 * F15;
      DM(32, I3) = F8;
      DM(0, I5) = R12;
      DM(16, I5) = R12;
      DM(32, I5) = R12;
      MODIFY(I3, 1);
n_in: MODIFY(I5, 1);

    F5 = 0.01; S5 = 0.01;               // leaky ReLU slope, both elements
    I4 = DM(MODEL + H_TABLE);
    R0 = DM(MODEL + H_LAYERS);
    LCNTR = R0, DO n_layer UNTIL LCE;
      R7 = DM(T_WT, I4);
      R2 = DM(T_W, I4);                 // this block's place in the rings
      M8 = R2;
      R0 = DM(T_DDR, I4);
      R0 = PASS R0;
      IF NE JUMP n_ddr;
      // ---- rings inside: the block's x into them and their guards, then
      // I0-I2 at the oldest tap of sample 0
      M0 = 1;
      L8 = DM(T_L, I4);
      M11 = DM(T_L, I4);
      R10 = DM(T_B0, I4);
      R9 = DM(T_STRIDE, I4);
      B8 = R10;
      I3 = X;
      CALL n_put;
      R10 = R10 + R9;
      B8 = R10;
      I3 = X + 16;
      CALL n_put;
      R10 = R10 + R9;
      B8 = R10;
      I3 = X + 32;
      CALL n_put;
      L8 = 0;
      M1 = R2;                          // (DAG1 wants a DAG1 modifier)
      M0 = DM(T_KD, I4);
      R10 = DM(T_B0, I4);
      B0 = R10;
      L0 = DM(T_L, I4);
      MODIFY(I0, M1);
      MODIFY(I0, M0);
      R10 = R10 + R9;
      B1 = R10;
      L1 = DM(T_L, I4);
      MODIFY(I1, M1);
      MODIFY(I1, M0);
      R10 = R10 + R9;
      B2 = R10;
      L2 = DM(T_L, I4);
      MODIFY(I2, M1);
      MODIFY(I2, M0);
      JUMP n_conv;
      // ---- rings in DDR2: the block's x into them, then each channel's K
      // taps of 16 into SCR, oldest first; I0-I2 then read SCR
n_ddr:
      M1 = DM(T_DM16, I4);
      M2 = DM(T_KD, I4);
      R6 = DM(T_K, I4);
      I8 = SCR;
      R10 = DM(T_B0, I4);
      R9 = DM(T_STRIDE, I4);
      B0 = R10;
      I3 = X;
      CALL n_far;
      R10 = R10 + R9;
      B0 = R10;
      I3 = X + 16;
      CALL n_far;
      R10 = R10 + R9;
      B0 = R10;
      I3 = X + 32;
      CALL n_far;
      L0 = 0;
      R0 = 16;
      R1 = LSHIFT R6 BY 4;              // 16 K: one channel's taps in SCR
      I0 = SCR;
      R3 = SCR;
      R3 = R3 + R1;
      I1 = R3;
      R3 = R3 + R1;
      I2 = R3;

n_conv:
      R0 = 16;                          // the next block's place
      R2 = R2 + R0;
      R0 = DM(T_L, I4);
      COMP(R2, R0);
      IF GE R2 = R2 - R0;
      DM(T_W, I4) = R2;
      R0 = DM(T_S, I4);
      M0 = R0;
      R1 = 2;
      R1 = R1 - R0;
      M2 = R1;                          // 2 - s
      R1 = R1 - R0;
      M1 = R1;                          // 2 - 2s
      M11 = DM(T_K, I4);
      M3 = DM(T_KS, I4);
      I3 = X;
      I5 = HS;
      I10 = IN;
      BIT SET MODE1 PEYEN | BDCST9;
      NOP;                              // the mode change takes an instruction
      LCNTR = 8, DO n_pair UNTIL LCE;
        I9 = R7;
        F1 = PM(I10, M10);              // in(t), in(t + 1)
        F8 = PM(I9, M9);                // a = bias + mixin * in, per output channel
        F4 = PM(I9, M9);
        F12 = F4 * F1;
        F8 = F8 + F12;
        F9 = PM(I9, M9);
        F4 = PM(I9, M9);
        F13 = F4 * F1;
        F9 = F9 + F13;
        F10 = PM(I9, M9);
        F4 = PM(I9, M9);
        F14 = F4 * F1;
        F10 = F10 + F14;
        R12 = R12 - R12;
        R13 = R13 - R13;
        R14 = R14 - R14;
        F0 = DM(I0, M0), F4 = PM(I9, M9);
        LCNTR = M11, DO n_tap UNTIL LCE;  // + w . taps: tap k, channel j, output i
          F12 = F0 * F4, F8 = F8 + F12, F4 = PM(I9, M9);
          F13 = F0 * F4, F9 = F9 + F13, F4 = PM(I9, M9);
          F14 = F0 * F4, F10 = F10 + F14, F0 = DM(I1, M0), F4 = PM(I9, M9);
          F12 = F0 * F4, F8 = F8 + F12, F4 = PM(I9, M9);
          F13 = F0 * F4, F9 = F9 + F13, F4 = PM(I9, M9);
          F14 = F0 * F4, F10 = F10 + F14, F0 = DM(I2, M0), F4 = PM(I9, M9);
          F12 = F0 * F4, F8 = F8 + F12, F4 = PM(I9, M9);
          F13 = F0 * F4, F9 = F9 + F13, F4 = PM(I9, M9);
n_tap:    F14 = F0 * F4, F10 = F10 + F14, F0 = DM(I0, M0), F4 = PM(I9, M9);
        F8 = F8 + F12;
        F9 = F9 + F13;
        F10 = F10 + F14;
        MODIFY(I9, -1);                 // the loop fetched one weight too many
        MODIFY(I0, M3);                 // and I0 one tap: on to the next pair, in two
        MODIFY(I0, M1);                 // steps each shorter than the ring
        MODIFY(I1, M3);
        MODIFY(I1, M2);
        MODIFY(I2, M3);
        MODIFY(I2, M2);
        F12 = F8 * F5;                  // leaky ReLU
        F8 = MAX(F8, F12);
        F13 = F9 * F5;
        F9 = MAX(F9, F13);
        F14 = F10 * F5;
        F10 = MAX(F10, F14);
        F1 = DM(0, I5);                 // hs += a
        F1 = F1 + F8;
        DM(0, I5) = F1;
        F1 = DM(16, I5);
        F1 = F1 + F9;
        DM(16, I5) = F1;
        F1 = DM(32, I5);
        F1 = F1 + F10;
        DM(32, I5) = F1;
        MODIFY(I5, 2);
        F11 = PM(I9, M9);               // x += bias1 + w1 . a, per output channel
        F4 = PM(I9, M9);
        F12 = F8 * F4;
        F11 = F11 + F12;
        F4 = PM(I9, M9);
        F12 = F9 * F4;
        F11 = F11 + F12;
        F4 = PM(I9, M9);
        F12 = F10 * F4;
        F11 = F11 + F12;
        F1 = DM(0, I3);
        F1 = F1 + F11;
        DM(0, I3) = F1;
        F11 = PM(I9, M9);
        F4 = PM(I9, M9);
        F12 = F8 * F4;
        F11 = F11 + F12;
        F4 = PM(I9, M9);
        F12 = F9 * F4;
        F11 = F11 + F12;
        F4 = PM(I9, M9);
        F12 = F10 * F4;
        F11 = F11 + F12;
        F1 = DM(16, I3);
        F1 = F1 + F11;
        DM(16, I3) = F1;
        F11 = PM(I9, M9);
        F4 = PM(I9, M9);
        F12 = F8 * F4;
        F11 = F11 + F12;
        F4 = PM(I9, M9);
        F12 = F9 * F4;
        F11 = F11 + F12;
        F4 = PM(I9, M9);
        F12 = F10 * F4;
        F11 = F11 + F12;
        F1 = DM(32, I3);
        F1 = F1 + F11;
        DM(32, I3) = F1;
n_pair: MODIFY(I3, 2);
      BIT CLR MODE1 PEYEN | BDCST9;
      NOP;
      L0 = 0;
      L1 = 0;
      L2 = 0;
n_layer: MODIFY(I4, T_SIZE);

    // ---- the head: 16 taps over the activation sums, through its own rings
    R2 = DM(MODEL + H_HW);
    M8 = R2;
    M0 = 1;
    R0 = 31;
    L8 = R0;
    M11 = R0;
    B8 = DM(MODEL + H_HB0);
    I3 = HS;
    CALL n_put;
    B8 = DM(MODEL + H_HB1);
    I3 = HS + 16;
    CALL n_put;
    B8 = DM(MODEL + H_HB2);
    I3 = HS + 32;
    CALL n_put;
    L8 = 0;
    M1 = R2;
    M0 = -15;
    B0 = DM(MODEL + H_HB0);
    L0 = 31;
    MODIFY(I0, M1);
    MODIFY(I0, M0);
    B1 = DM(MODEL + H_HB1);
    L1 = 31;
    MODIFY(I1, M1);
    MODIFY(I1, M0);
    B2 = DM(MODEL + H_HB2);
    L2 = 31;
    MODIFY(I2, M1);
    MODIFY(I2, M0);
    R0 = 16;
    R2 = R2 + R0;
    R0 = 31;
    COMP(R2, R0);
    IF GE R2 = R2 - R0;
    DM(MODEL + H_HW) = R2;
    M0 = 1;
    M1 = -15;
    M2 = -14;
    R7 = DM(MODEL + H_HEAD);
    F2 = DM(MODEL + H_SCALE);
    S2 = R2;
    F3 = DM(N_LEVEL);
    S3 = R3;
    BIT SET MODE1 PEYEN | BDCST9;
    NOP;
    LCNTR = 8, DO n_hpair UNTIL LCE;
      I9 = R7;
      F8 = PM(I9, M9);                  // the head's bias
      R12 = R12 - R12;
      F0 = DM(I0, M0), F4 = PM(I9, M9);
      LCNTR = 16, DO n_htap UNTIL LCE;
        F12 = F0 * F4, F8 = F8 + F12, F0 = DM(I1, M0), F4 = PM(I9, M9);
        F12 = F0 * F4, F8 = F8 + F12, F0 = DM(I2, M0), F4 = PM(I9, M9);
n_htap: F12 = F0 * F4, F8 = F8 + F12, F0 = DM(I0, M0), F4 = PM(I9, M9);
      F8 = F8 + F12;
      F8 = F8 * F2;                     // scale, then the level
      F8 = F8 * F3;
      PM(I11, M10) = F8;                // out(t), out(t + 1)
      MODIFY(I0, M1);
      MODIFY(I1, M2);
      MODIFY(I2, M2);
      NOP;
n_hpair: NOP;
    BIT CLR MODE1 PEYEN | BDCST9;
    NOP;

    // ---- the mix: the model's output x its fade-in gain + the tail x its
    // fade-out gain (each FADE_TAB at the block's start, in a line to its end),
    // kept in HIST; then the tone stack (transposed direct form II: y = b0 x + s1,
    // s1 = b1 x - a1 y + s2, s2 = b2 x - a2 y). Its state is never cleared after
    // boot: the tail plays through it.
n_mix:
    B0 = HIST;
    L0 = 512;
    I0 = DM(N_HW);
    B5 = HIST;
    L5 = 512;
    I5 = DM(N_MR);
    M0 = 1;
    M1 = -1;
    I3 = FADE_TAB;
    F1 = 0.0625;
    M2 = DM(N_GAIN);
    F2 = DM(M2, I3);
    M2 = DM(N_G1);
    F3 = DM(M2, I3);
    F3 = F3 - F2;
    F3 = F3 * F1;
    R0 = DM(N_MG);
    M2 = R0;
    F6 = DM(M2, I3);
    R0 = R0 - 1;
    IF LT R0 = R0 + 1;
    DM(N_MG) = R0;
    M2 = R0;
    F7 = DM(M2, I3);
    F7 = F7 - F6;
    F7 = F7 * F1;
    I11 = B11;
    LCNTR = 16, DO n_eqx UNTIL LCE;
      F8 = PM(0, I11);
      F8 = F8 * F2;
      F0 = DM(I5, M1);
      F0 = F0 * F6;
      F8 = F8 + F0;
      DM(I0, M0) = F8;
      I3 = EQ_C;
      I4 = EQ_S;
      LCNTR = 4, DO n_eqb UNTIL LCE;
        F4 = DM(0, I3);                 // b0
        F12 = F4 * F8;
        F0 = DM(0, I4);                 // s1
        F9 = F12 + F0;                  // y
        F4 = DM(1, I3);                 // b1 x - a1 y + s2
        F12 = F4 * F8;
        F4 = DM(3, I3);
        F13 = F4 * F9;
        F12 = F12 + F13;
        F0 = DM(1, I4);
        F12 = F12 + F0;
        DM(0, I4) = F12;
        F4 = DM(2, I3);                 // b2 x - a2 y
        F12 = F4 * F8;
        F4 = DM(4, I3);
        F13 = F4 * F9;
        F12 = F12 + F13;
        DM(1, I4) = F12;
        F8 = PASS F9;
        MODIFY(I3, 5);
n_eqb:  MODIFY(I4, 2);
      F2 = F2 + F3;
      F6 = F6 + F7;
      PM(I11, M9) = F8;
n_eqx: NOP;
    R0 = DM(N_G1);
    DM(N_GAIN) = R0;
    DM(N_HW) = I0;
    DM(N_MR) = I5;

    // METER (nam_lite.py --meter puts code here)
n_back:
    R0 = DM(N_SAVE + 1);
    R1 = DM(N_SAVE + 2);
    R2 = DM(N_SAVE + 3);
    R3 = DM(N_SAVE + 4);
    R4 = DM(N_SAVE + 5);
    R5 = DM(N_SAVE + 6);
    R6 = DM(N_SAVE + 7);
    R7 = DM(N_SAVE + 8);
    R8 = DM(N_SAVE + 9);
    R9 = DM(N_SAVE + 10);
    R10 = DM(N_SAVE + 11);
    R11 = DM(N_SAVE + 12);
    R12 = DM(N_SAVE + 13);
    R13 = DM(N_SAVE + 14);
    R14 = DM(N_SAVE + 15);
    R15 = DM(N_SAVE + 16);
    S0 = DM(N_SAVE + 17);
    S1 = DM(N_SAVE + 18);
    S2 = DM(N_SAVE + 19);
    S3 = DM(N_SAVE + 20);
    S4 = DM(N_SAVE + 21);
    S5 = DM(N_SAVE + 22);
    S8 = DM(N_SAVE + 23);
    S9 = DM(N_SAVE + 24);
    S10 = DM(N_SAVE + 25);
    S11 = DM(N_SAVE + 26);
    S12 = DM(N_SAVE + 27);
    S13 = DM(N_SAVE + 28);
    S14 = DM(N_SAVE + 29);
    L0 = 0; L1 = 0; L2 = 0; L3 = 0; L4 = 0; L5 = 0;
    L8 = 0; L9 = 0; L10 = 0; L11 = 0;
    B0 = DM(N_SAVE + 30);
    I0 = DM(N_SAVE + 31);
    B1 = DM(N_SAVE + 32);
    B2 = DM(N_SAVE + 33);
    B3 = DM(N_SAVE + 34);
    I3 = DM(N_SAVE + 35);
    B4 = DM(N_SAVE + 36);
    I4 = DM(N_SAVE + 37);
    B5 = DM(N_SAVE + 38);
    I5 = DM(N_SAVE + 39);
    M0 = DM(N_SAVE + 40);
    M1 = DM(N_SAVE + 41);
    M2 = DM(N_SAVE + 42);
    M3 = DM(N_SAVE + 43);
    M4 = DM(N_SAVE + 44);
    B8 = DM(N_SAVE + 45);
    I8 = DM(N_SAVE + 46);
    B9 = DM(N_SAVE + 47);
    I9 = DM(N_SAVE + 48);
    B10 = DM(N_SAVE + 49);
    I10 = DM(N_SAVE + 50);
    B11 = DM(N_SAVE + 51);
    I11 = DM(N_SAVE + 52);
    M8 = DM(N_SAVE + 53);
    M9 = DM(N_SAVE + 54);
    M10 = DM(N_SAVE + 55);
    M11 = DM(N_SAVE + 56);
    MODE1 = DM(N_SAVE + 0);
    NOP;
    RTS (LR);

// A crossfade starts: the tail from the last output (full gain, 17: it holds
// for the load block), the model silent until it has loaded. Leaves R0 = 0.
n_cut:
    R0 = 17;
    DM(N_MG) = R0;
    R0 = DM(N_HW);
    R0 = R0 - 1;
    R1 = HIST;
    R2 = 512;
    COMP(R0, R1);
    IF LT R0 = R0 + R2;
    DM(N_MR) = R0;
    R0 = 0;
    DM(N_GAIN) = R0;
    RTS;

// The 16 words at I3 (DM, step M0 = 1) into the ring B8 (L8 = its length,
// already set) from offset M8, then its guard (B8 + M11, M11 = the length) =
// its first word.
n_put:
    MODIFY(I8, M8);
    F0 = DM(I3, M0);
    LCNTR = 16, DO n_putw UNTIL LCE;
n_putw: F0 = DM(I3, M0), PM(I8, M9) = F0;
    R1 = L8;                            // (R1: F0 is R0)
    L8 = 0;
    I8 = B8;
    F0 = PM(0, I8);
    PM(M11, I8) = F0;
    L8 = R1;
    RTS;

// The 16 words at I3 into the DDR2 ring B0 (its length from T_L) from offset
// R2; then its K = R6 taps of 16, oldest first (from M8 + M2, M2 = T_KD, each
// M1 = d - 16 past the last one's end), to I8 in SCR.
n_far:
    L0 = DM(T_L, I4);
    M4 = R2;                            // w (DAG1 wants a DAG1 modifier; M4 is set again after)
    MODIFY(I0, M4);
    LCNTR = 16, DO n_farw UNTIL LCE;
      F0 = DM(I3, 1);
n_farw: DM(I0, 1) = F0;
    I0 = B0;
    MODIFY(I0, M4);
    MODIFY(I0, M2);
    LCNTR = R6, DO n_fark UNTIL LCE;
      LCNTR = 16, DO n_fart UNTIL LCE;
        F0 = DM(I0, 1);
n_fart: PM(I8, M9) = F0;
n_fark: MODIFY(I0, M1);
    RTS;

.section dm 0xe4890                 // N_INIT: 0 at boot, so the first call clears the rings;
    .word 0, 0, 0, 0                // N_LEVEL; N_OWNER, N_TICK: no owner yet;
    .word 0, 0, 0, 0, 0             // N_T0, N_MCNT, N_SIG (no model loaded), N_GAIN, N_G1
    .word 0, 0x327500, 0x327500     // N_MG, N_MR, N_HW (HIST)
