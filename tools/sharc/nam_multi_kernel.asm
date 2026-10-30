// nam_multi_kernel.asm - NAM A2 Lite (3 channels) for several blocks at once, each
// with its own capture. A primitive of the stock HX Stomp 3.80 firmware, called by
// the stock dispatcher once per 16-sample block (sdk/CONTRACT.md). nam_multi.py puts
// the addresses in (the .equ block at "EQUS") and adds the shared tables.
//
// The arithmetic of a layer, the head, the crossfade and the tone stack is
// nam-a2-lite's (nam_lite_kernel.asm), so each block's output is nam_a2.asm's bit
// for bit on its own model. What is new is where the memory comes from:
//
// - Slots. The free internal memory holds NSLOTS slots; each holds one model
//   (weights, silence state), its short rings, its crossfade and tone-stack
//   state. An instance keeps its slot number + 1 in DM(P_SLOT, I0) (0 when it is
//   created). A slot's owner word is the I0 of the instance that has it; every
//   call writes the global call count into its slot's LAST word. An instance
//   without a slot takes, in this order: a slot whose owner is its own I0 (it was
//   created again at the same place), a free slot, a slot whose owner has not run
//   since this instance's own last call (removed). With none, it passes its input
//   through.
// - The long rings (d >= FAR_D) are in the instance's own SDRAM block (DM(2, I3)
//   words 6 and 7). Per far layer, external-port DMA channel 0 brings each
//   channel's K-1 older tap windows (16 words each) into a staging buffer, as a
//   chain of 15 TCBs and a sentinel TCB that copies MAGIC from the SDRAM block
//   into a flag word: the flag says the chain is done (polling DMAC0 during a chain
//   is unreliable, HRM p. 2-31). Two staging buffers: the chain for far layer j+1
//   runs while layer j computes. The newest tap is this block's x, copied in by the
//   core. After the last far layer has its x, one write chain puts every far
//   layer's new 16 words back into its rings (and a sequence number after them,
//   which the core reads back from the SDRAM block to know the chain is done).
//   A ring is L' = (K-1)d + 16 rounded up to 16 words, so a block's write never
//   wraps, plus a 16-word mirror of its first words, so no tap window wraps either:
//   the core writes the mirror when the write offset is 0.
// - Windows older than the first block since the model was loaded are the
//   model's silence state: the core writes it over them (S_T counts the samples
//   written since the load), so a model starts from the silence state without
//   filling 19k words of SDRAM.
// - A DMA that does not finish within POLLMAX polls is switched off (HRM p. 3-124):
//   the block is silent, the slot starts again (S_INIT = 0), and every instance is
//   silent for BACKOFF_N calls. A channel found busy, or its interrupt unmasked,
//   does the same. Nothing waits without a bound.
//
// Knobs as nam-a2-lite: Drive DM(5), Ch Vol DM(6), Model DM(7) (0 the built-in
// model, now none: silence), 1..128 a User IR slot), Bass..Presence DM(8..11); and Polarity
// DM(P_PHASE) (a bool: not 0 inverts the output, by negating Ch Vol's gain).
// Drive is x the slot's S_TRIM, set on each load from the model's IR word 5
// (10^(-input_level_dbu/20); 0 none, as the built-in model and older .wav files)
// x STOMP_GAIN (10^(STOMP_DBU/20), nam_lite.py): as nam-a2-lite's N_TRIM.

.equ PEYEN,    0x200000
.equ BDCST9,   0x400000
.equ CBUFEN,   0x1000000
.equ SIGCHK_N, 64                       // the model check's period in calls, at most

// EQUS (nam_multi.py puts the layout here)

.section pm 0x0c4ef8

CUSTOM_AMP_ENTRY:
    DM(SAVE + 0) = MODE1;
    BIT CLR MODE1 PEYEN | BDCST9;
    BIT SET MODE1 CBUFEN;
    DM(SAVE + 1) = R0;
    DM(SAVE + 2) = R1;
    DM(SAVE + 3) = R2;
    DM(SAVE + 4) = R3;
    DM(SAVE + 5) = R4;
    DM(SAVE + 6) = R5;
    DM(SAVE + 7) = R6;
    DM(SAVE + 8) = R7;
    DM(SAVE + 9) = R8;
    DM(SAVE + 10) = R9;
    DM(SAVE + 11) = R10;
    DM(SAVE + 12) = R11;
    DM(SAVE + 13) = R12;
    DM(SAVE + 14) = R13;
    DM(SAVE + 15) = R14;
    DM(SAVE + 16) = R15;
    DM(SAVE + 17) = S0;
    DM(SAVE + 18) = S1;
    DM(SAVE + 19) = S2;
    DM(SAVE + 20) = S3;
    DM(SAVE + 21) = S4;
    DM(SAVE + 22) = S5;
    DM(SAVE + 23) = S8;
    DM(SAVE + 24) = S9;
    DM(SAVE + 25) = S10;
    DM(SAVE + 26) = S11;
    DM(SAVE + 27) = S12;
    DM(SAVE + 28) = S13;
    DM(SAVE + 29) = S14;
    DM(SAVE + 30) = B0;
    DM(SAVE + 31) = I0;
    DM(SAVE + 32) = B1;
    DM(SAVE + 33) = B2;
    DM(SAVE + 34) = B3;
    DM(SAVE + 35) = I6;
    DM(SAVE + 36) = B4;
    DM(SAVE + 37) = I4;
    DM(SAVE + 38) = B5;
    DM(SAVE + 39) = I5;
    DM(SAVE + 40) = M0;
    DM(SAVE + 41) = M1;
    DM(SAVE + 42) = M2;
    DM(SAVE + 43) = M3;
    DM(SAVE + 44) = M4;
    DM(SAVE + 45) = B8;
    DM(SAVE + 46) = I8;
    DM(SAVE + 47) = B9;
    DM(SAVE + 48) = I9;
    DM(SAVE + 49) = B10;
    DM(SAVE + 50) = I10;
    DM(SAVE + 51) = B11;
    DM(SAVE + 52) = I11;
    DM(SAVE + 53) = M8;
    DM(SAVE + 54) = M9;
    DM(SAVE + 55) = M10;
    DM(SAVE + 56) = M11;
    DM(SAVE + 57) = S6;
    DM(SAVE + 58) = S7;
    DM(SAVE + 59) = M5;
    DM(SAVE + 60) = M6;
    DM(SAVE + 61) = M7;
    DM(SAVE + 62) = I12;                // (fcopy reads X through PM with I12)
    DM(SAVE + 63) = L12;
    L0 = 0; L1 = 0; L2 = 0; L3 = 0; L4 = 0; L5 = 0;
    L8 = 0; L9 = 0; L10 = 0; L11 = 0; L12 = 0;
    B10 = I1;                           // the block's input and output, through PM
    B11 = I2;
    M9 = 1; M10 = 2;
// METER_ENTRY

    R0 = 0;
    DM(G_JOBS) = R0;                    // no DMA jobs in this call (yet)
    R0 = DM(REP + R_CALLS);             // the global call count: slots' LAST words
    R0 = R0 + 1;
    DM(REP + R_CALLS) = R0;
    R12 = R0;                           // R12 = this call's count until the layers

    // ---- the instance's slot
    R0 = I0;
    R1 = DM(P_SLOT, I0);
    R1 = PASS R1;
    IF EQ JUMP m_claim;
    R2 = SLOTTAB - 1;
    R1 = R1 + R2;
    I5 = R1;
    R2 = DM(0, I5);
    I6 = R2;
    R2 = DM(S_OWNER, I6);
    COMP(R2, R0);
    IF EQ JUMP m_slot;
    R1 = 0;                             // taken over while this one did not run: look again
    DM(P_SLOT, I0) = R1;
m_claim:
    R4 = DM(P_SEEN, I0);                // the count at this instance's last call
    R5 = DM(P_MET, I0);                 // 0 on its first call
    DM(P_SEEN, I0) = R12;
    R1 = 1;
    DM(P_MET, I0) = R1;
    I5 = SLOTTAB;                       // 1) a slot that this I0 owns already
    R6 = NSLOTS;
m_c1: R2 = DM(I5, 1);
    I6 = R2;
    R2 = DM(S_OWNER, I6);
    COMP(R2, R0);
    IF EQ JUMP m_take;
    R6 = R6 - 1;
    IF NE JUMP m_c1;
    I5 = SLOTTAB;                       // 2) a free slot
    R6 = NSLOTS;
m_c2: R2 = DM(I5, 1);
    I6 = R2;
    R2 = DM(S_OWNER, I6);
    R2 = PASS R2;
    IF EQ JUMP m_take;
    R6 = R6 - 1;
    IF NE JUMP m_c2;
    R5 = PASS R5;                       // 3) a slot whose owner has not run since this
    IF EQ JUMP m_noslot;                //    instance's last call (its block is gone)
    I5 = SLOTTAB;
    R6 = NSLOTS;
m_c3: R2 = DM(I5, 1);
    I6 = R2;
    R2 = DM(S_LAST, I6);
    COMP(R2, R4);
    IF LT JUMP m_take;
    R6 = R6 - 1;
    IF NE JUMP m_c3;
m_noslot:
    R0 = DM(REP + R_NOSLOT);
    R0 = R0 + 1;
    DM(REP + R_NOSLOT) = R0;
    JUMP m_pass;
m_take:
    R1 = I5;                            // I5 is one past the slot's entry: slot + 1
    R2 = SLOTTAB;
    R1 = R1 - R2;
    DM(P_SLOT, I0) = R1;
    DM(S_OWNER, I6) = R0;
    R1 = 0;
    DM(S_INIT, I6) = R1;
    R0 = DM(REP + R_CLAIMS);
    R0 = R0 + 1;
    DM(REP + R_CLAIMS) = R0;
    R1 = I5;                            // the report's owner word of this slot
    R2 = SLOTTAB + 1;
    R1 = R1 - R2;
    R2 = REP + R_OWNERS;
    R1 = R1 + R2;
    I5 = R1;
    R1 = I0;
    DM(0, I5) = R1;
m_slot:
    DM(S_LAST, I6) = R12;

    // ---- the instance's SDRAM block (the far rings, HIST, the sentinels)
    R0 = DM(HXK_ENTRY_INST, I3);
    I5 = R0;
    R1 = DM(HXK_INST_SDRAM, I5);
    R2 = DM(HXK_INST_SDRAM_END, I5);
    R2 = R2 - R1;
    R3 = SDR_NEED;
    COMP(R2, R3);
    IF LT JUMP m_nosdr;
    DM(G_SDR) = R1;
    R2 = DM(S_SDR, I6);
    COMP(R1, R2);
    IF EQ JUMP m_sdrok;
    DM(S_SDR, I6) = R1;                 // another block: start again
    R1 = 0;
    DM(S_INIT, I6) = R1;
m_sdrok:
    R0 = DM(REP + R_BACKOFF);           // after a DMA failure every instance is silent a while
    R0 = PASS R0;
    IF EQ JUMP m_nobo;
    R0 = R0 - 1;
    DM(REP + R_BACKOFF) = R0;
    R0 = 0;
    DM(S_INIT, I6) = R0;
    JUMP m_silent;
m_nobo:
    R0 = DM(DMAC0);                     // the channel idle and its interrupt masked, or nothing
    R1 = BUSYM;
    R1 = R0 AND R1;
    IF NE JUMP m_busy;
    R0 = LRPTL;
    R1 = EP0IMSK;
    R1 = R0 AND R1;
    IF EQ JUMP m_idle;
m_busy:
    R0 = DM(REP + R_SKIPS);
    R0 = R0 + 1;
    DM(REP + R_SKIPS) = R0;
    JUMP m_fail;
m_idle:
    R0 = DM(S_INIT, I6);
    R0 = PASS R0;
    IF NE JUMP m_ready;
    CALL m_init;

m_ready:
    F0 = DM(5, I0);                     // Drive: the input gain, from DRIVE_TAB by its step
    F1 = 100.0;
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
    F0 = DM(S_TRIM, I6);                // x the slot's model's input trim (0: none):
    F0 = PASS F0;                       // its capture's level against the Stomp's
    IF NE F14 = F14 * F0;
    F0 = DM(6, I0);
    F0 = F0 * F0;
    F1 = 4.0;
    F0 = F0 * F1;
    R1 = DM(P_PHASE, I0);               // Polarity: Inverted negates the level, so the
    R1 = PASS R1;                       // head's output and all that follows it (the
    IF NE F0 = -F0;                     // crossfade and the tone stack are linear)
    DM(G_LEVEL) = F0;                   // output level, 4 k^2

    // ---- the model: 1..128 a User IR slot; 0 (the knob's range is 1..128) or a slot
    // without a NAM capture: silence. Its check (~20 SDRAM reads) only after a knob
    // write, with no model known, or every SIGCHK_N calls; else the slot's model stands.
    // P_SIGN is 0 whenever S_SIG is (m_init, n_zero), so no model known means a check.
    R0 = DM(3, I0);
    R0 = PASS R0, R1 = DM(P_SIGN, I0);
    IF NE JUMP n_chk;
    R1 = R1 - 1;
    IF GT JUMP n_same (DB);
    DM(P_SIGN, I0) = R1;
n_chk: R0 = SIGCHK_N;                   // (also the branch's second delay slot)
    DM(P_SIGN, I0) = R0;
    R0 = DM(7, I0);
    R1 = 0x800000;
    COMP(R0, R1);
    IF LT JUMP n_int;                   // an integer (a float >= 2^-126 is not)
    R0 = TRUNC F0;
n_int:
    R1 = 1;
    R0 = R0 - R1;
    IF LT JUMP n_none;
    R1 = 128;
    COMP(R0, R1);
    IF GE JUMP n_none;
    R1 = IR_FLAG;
    R1 = R1 + R0;
    I3 = R1;
    R1 = DM(0, I3);
    R1 = PASS R1;
    IF EQ JUMP n_none;
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
    F3 = 1.8271484375;                  // 1871 / 1024
    COMP(F2, F3);
    IF NE JUMP n_none;
    R8 = R1;
    I3 = R8;
    R5 = R8;
    LCNTR = 16, DO n_sigw UNTIL LCE;
      R6 = DM(I3, -1);
n_sigw: R5 = R5 + R6;
    R6 = DM(S_SIG, I6);
    COMP(R5, R6);
    IF EQ JUMP n_same;
    DM(S_SIG, I6) = R5;                 // another model: crossfade to it, and load it
    CALL n_cut;
    CALL ld_model;
    R0 = DM(DMA_FAIL);
    R0 = PASS R0;
    IF NE JUMP m_fail;
    JUMP n_zero;
n_same:
    R0 = DM(S_GAIN, I6);
    R0 = R0 + 1;
    R1 = 16;
    R0 = MIN(R0, R1);
    DM(S_G1, I6) = R0;
    JUMP n_have;

n_have:
    // ---- the tone knobs, each step's five coefficients from EQ_TAB when it moves
    // (only after a knob write: the stock writer sets DM(3); or a fresh slot)
    R0 = DM(3, I0);
    R1 = DM(S_EQDIRTY, I6);
    R0 = R0 OR R1;
    IF EQ JUMP n_eqdone;
    R0 = 0;
    DM(3, I0) = R0;
    DM(S_EQDIRTY, I6) = R0;
    I3 = I0;
    MODIFY(I3, 8);
    R0 = I6;
    R1 = S_EQIDX;
    R1 = R0 + R1;
    I4 = R1;
    R1 = S_EQC;
    R1 = R0 + R1;
    I5 = R1;
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
      R1 = R0 + R0;
      R1 = R1 + R1;
      R1 = R1 + R0;
      R1 = R1 + R9;
      I0 = R1;                          // (I0 is free: the knobs are read)
      I2 = I5;
      LCNTR = 5, DO n_eqw UNTIL LCE;
        R1 = DM(I0, 1);
n_eqw:  DM(I2, 1) = R1;
n_eqs:
      MODIFY(I4, 1);
      MODIFY(I5, 5);
      R1 = 505;
      R9 = R9 + R1;
      NOP;
n_eqk: NOP;
n_eqdone:

    // ---- the DMA jobs of this block, then the model
    R0 = 0;
    DM(J_NEXT) = R0;
    DM(J_BUSY) = R0;
    DM(J_DONE) = R0;
    DM(EVENTS) = R0;
    DM(DMA_FAIL) = R0;
    DM(REP + R_POLLS) = R0;
    CALL pump;                          // the first far layer's taps

    I3 = X + 16;                        // x = rechannel * in, hs = 0, two samples at a time
    I5 = HS + 16;
    I0 = IN;
    I10 = B10;
    M7 = 2;
    R0 = I6;
    R1 = S_STREAM;
    R0 = R0 + R1;
    I4 = R0;
    R1 = DM(0, I4);
    R2 = DM(1, I4);
    R3 = DM(2, I4);
    S1 = R1;
    S2 = R2;
    S3 = R3;
    S14 = R14;
    R12 = 0;
    S12 = R12;
    BIT SET MODE1 PEYEN;
    NOP;
    LCNTR = 8, DO n_in UNTIL LCE;
      F13 = PM(I10, M10);
      F13 = F13 * F14;
      F8 = F1 * F13, DM(I0, M7) = F13;
      F9 = F2 * F13, DM(-16, I3) = F8;
      F10 = F3 * F13, DM(0, I3) = F9;
      DM(16, I3) = F10;
      DM(-16, I5) = F12;
      DM(0, I5) = F12;
      DM(16, I5) = F12;
      MODIFY(I3, M7);
n_in: MODIFY(I5, M7);
    BIT CLR MODE1 PEYEN;
    NOP;

    F5 = 0.01; S5 = 0.01;               // leaky ReLU slope, both elements
    M5 = 16;                            // the pair loop's steps through X
    M6 = -30;
    I4 = TABLE;
    LCNTR = NLAYERS, DO n_layer UNTIL LCE;
      CALL pump;
      M4 = DM(T_LW, I4);
      R2 = DM(M4, I6);                  // this block's place in the rings
      M8 = R2;
      R0 = DM(T_FAR, I4);
      R0 = PASS R0;
      IF NE JUMP n_ddr;
      // ---- rings in the slot: the block's x into them and their guards, then
      // I0-I2 at the oldest tap of sample 0
      M0 = 1;
      L8 = DM(T_L, I4);
      M11 = DM(T_L, I4);
      R10 = DM(T_RB, I4);
      R0 = I6;
      R10 = R10 + R0;
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
      M1 = R2;
      M0 = DM(T_KD, I4);
      R10 = DM(T_RB, I4);
      R0 = I6;
      R10 = R10 + R0;
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
      // ---- rings in SDRAM: wait for this layer's taps, add the newest, read them
n_ddr:
      CALL fwait;
      CALL fcopy;
      L0 = 0;
      L1 = 0;
      L2 = 0;
      R3 = DM(T_SB, I4);
      I0 = R3;
      R1 = 96;
      R3 = R3 + R1;
      I1 = R3;
      R3 = R3 + R1;
      I2 = R3;

n_conv:
      M4 = DM(T_LW, I4);
      R2 = DM(M4, I6);
      R0 = 16;                          // the next block's place
      R2 = R2 + R0;
      R0 = DM(T_L, I4);
      COMP(R2, R0);
      IF GE R2 = R2 - R0;
      DM(M4, I6) = R2;
      R15 = DM(T_WT, I4);               // this layer's weights
      R0 = I6;
      R15 = R15 + R0;
      I9 = R15;
      M8 = DM(T_NW, I4);                // back to them after each pair: -(words a layer)
      R2 = DM(T_FAR, I4);               // a near layer: its weights into WBUF (Block 2), so its
      R2 = PASS R2;                     // taps' ring reads (Block 3) do not meet them in one block
      IF NE JUMP n_wfar;                // (a far layer's taps read Block 2's staging buffers)
      I3 = R15;
      I9 = WBUF;
      R0 = M8;
      R0 = -R0;
      R1 = 3;
      R0 = R0 + R1;
      R0 = LSHIFT R0 BY -2;             // word pairs / 2 (WBUF_N: up to 3 more words read
      R0 = R0 - 1;                      // and written), the loop's count
      BIT SET MODE1 PEYEN;              // two words a move (M7 = M10 = 2), in F2 and F3
      NOP;                              // by turns: no store of a register loaded just before
      F2 = DM(I3, M7);
      F3 = DM(I3, M7);
      LCNTR = R0, DO n_wc UNTIL LCE;
        F2 = DM(I3, M7), PM(I9, M10) = F2;
n_wc:   F3 = DM(I3, M7), PM(I9, M10) = F3;
      PM(I9, M10) = F2;
      PM(I9, M10) = F3;
      BIT CLR MODE1 PEYEN;
      I9 = WBUF;
n_wfar:
      R0 = DM(T_S, I4);
      M0 = R0;
      R1 = 2;
      R1 = R1 - R0;
      M2 = R1;                          // 2 - s
      R1 = R1 - R0;
      M1 = R1;                          // 2 - 2s
      M11 = DM(T_K, I4);
      M3 = DM(T_KS, I4);
      M4 = 0;
      R3 = 0;                           // F3, F7: +0 in both elements (the zero the
      S3 = R3;                          // reference adds before the taps)
      R7 = 0;
      S7 = R7;
      I3 = X;                           // x: channel 0, then +16 each (M5), -30 to the next pair (M6)
      I5 = HS + 16;                     // hs: channel 1, the others at -16 and +16
      R15 = I4;                         // (the table pointer, while I4 reads IN)
      I4 = IN;
      BIT SET MODE1 PEYEN | BDCST9;
      NOP;
      LCNTR = 8, DO n_pair UNTIL LCE;
        F1 = DM(I4, M7), F8 = PM(I9, M9);   // in(t), in(t + 1); a = bias + mixin * in, + 0
        F4 = PM(I9, M9);
        F12 = F1 * F4, F9 = PM(I9, M9);
        F12 = F3 * F7, F8 = F8 + F12, F4 = PM(I9, M9);
        F13 = F1 * F4, F10 = PM(I9, M9);
        F13 = F3 * F7, F9 = F9 + F13, F4 = PM(I9, M9);
        F14 = F1 * F4, F0 = DM(I0, M0), F4 = PM(I9, M9);
        F14 = F3 * F7, F10 = F10 + F14;
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
        // (F4 holds the first 1x1 weight: the loop read one too many)
        F8 = F8 + F12, MODIFY(I0, M3);  // I0-I2 on to the next pair, in two steps each
        F9 = F9 + F13, MODIFY(I0, M1);  // shorter than the ring
        F10 = F10 + F14, MODIFY(I1, M3);
        F12 = F8 * F5, MODIFY(I1, M2);  // leaky ReLU
        F13 = F9 * F5, MODIFY(I2, M3);
        F14 = F10 * F5, MODIFY(I2, M2);
        F0 = MAX(F8, F12), F11 = DM(-16, I5);
        F1 = MAX(F9, F13), F12 = DM(0, I5);
        F2 = MAX(F10, F14), F13 = DM(16, I5);
        F11 = F11 + F0, F6 = PM(I9, M9);    // hs += a
        F12 = F12 + F1, DM(-16, I5) = F11;
        F13 = F13 + F2, DM(0, I5) = F12;
        F8 = PASS F4, DM(16, I5) = F13;     // x += bias1 + w1 . a, per output channel
        F12 = F0 * F6, F6 = PM(I9, M9);
        NOP;                            // (two NOPs: no instruction-cache set gets a third
        NOP;                            // PM-data instruction of this loop, nam_stalls.py)
        F12 = F1 * F6, F8 = F8 + F12, F6 = PM(I9, M9);
        F12 = F2 * F6, F8 = F8 + F12, F9 = PM(I9, M9);
        F8 = F8 + F12, F13 = DM(I3, M4), F6 = PM(I9, M9);
        F12 = F0 * F6, F13 = F8 + F13, F6 = PM(I9, M9);
        F12 = F1 * F6, F9 = F9 + F12, DM(I3, M5) = F13, F6 = PM(I9, M9);
        F12 = F2 * F6, F9 = F9 + F12, F10 = PM(I9, M9);
        F9 = F9 + F12, F13 = DM(I3, M4), F6 = PM(I9, M9);
        F12 = F0 * F6, F13 = F9 + F13, F6 = PM(I9, M9);
        F12 = F1 * F6, F10 = F10 + F12, DM(I3, M5) = F13, F6 = PM(I9, M9);
        F12 = F2 * F6, F10 = F10 + F12, F13 = DM(I3, M4);
        F10 = F10 + F12, MODIFY(I5, M7);
        F13 = F10 + F13, MODIFY(I9, M8);
n_pair: DM(I3, M6) = F13;
      BIT CLR MODE1 PEYEN | BDCST9;
      I4 = R15;
      L0 = 0;
      L1 = 0;
      L2 = 0;
      R0 = DM(T_FAR, I4);               // a far layer computed: its staging buffer is free
      R0 = PASS R0;
      R0 = DM(EVENTS);
      R1 = 1;
      IF NE R0 = R0 + R1;
      DM(EVENTS) = R0;
n_layer: MODIFY(I4, T_SIZE);

    // ---- the head: 16 taps over the activation sums, through its own rings
    R2 = DM(S_HHW, I6);
    M8 = R2;
    M0 = 1;
    R0 = 31;
    L8 = R0;
    M11 = R0;
    R10 = I6;
    R1 = S_HB0;
    R1 = R1 + R10;
    B8 = R1;
    I3 = HS;
    CALL n_put;
    R1 = S_HB1;
    R1 = R1 + R10;
    B8 = R1;
    I3 = HS + 16;
    CALL n_put;
    R1 = S_HB2;
    R1 = R1 + R10;
    B8 = R1;
    I3 = HS + 32;
    CALL n_put;
    L8 = 0;
    M1 = R2;
    M0 = -15;
    R1 = S_HB0;
    R1 = R1 + R10;
    B0 = R1;
    L0 = 31;
    MODIFY(I0, M1);
    MODIFY(I0, M0);
    R1 = S_HB1;
    R1 = R1 + R10;
    B1 = R1;
    L1 = 31;
    MODIFY(I1, M1);
    MODIFY(I1, M0);
    R1 = S_HB2;
    R1 = R1 + R10;
    B2 = R1;
    L2 = 31;
    MODIFY(I2, M1);
    MODIFY(I2, M0);
    R0 = 16;
    R2 = R2 + R0;
    R0 = 31;
    COMP(R2, R0);
    IF GE R2 = R2 - R0;
    DM(S_HHW, I6) = R2;
    M0 = 1;
    M1 = -15;
    M2 = -14;
    R7 = S_STREAM + ST_HEAD;
    R7 = R7 + R10;
    F2 = DM(S_STREAM + ST_SCALE, I6);
    S2 = R2;
    F3 = DM(G_LEVEL);
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
    L0 = 0;
    L1 = 0;
    L2 = 0;

    R0 = 1;
    DM(G_JOBS) = R0;

    // ---- the mix: the model's output x its fade-in gain + the tail (HIST played
    // backwards) x its fade-out gain, into HIST; then the tone stack
n_mix:
    R0 = DM(G_SDR);
    R1 = HIST_OFF;
    R0 = R0 + R1;
    B0 = R0;
    L0 = 512;
    M2 = DM(S_HW, I6);
    MODIFY(I0, M2);
    B5 = R0;
    L5 = 512;
    M2 = DM(S_MR, I6);
    MODIFY(I5, M2);
    M0 = 1;
    M1 = -1;
    M4 = 0;
    I3 = FADE_TAB;
    F1 = 0.0625;
    M2 = DM(S_GAIN, I6);
    F2 = DM(M2, I3);
    M2 = DM(S_G1, I6);
    F3 = DM(M2, I3);
    F3 = F3 - F2;
    F3 = F3 * F1;
    R0 = DM(S_MG, I6);
    R5 = R0;                            // the tail plays this block (MG > 0)
    M2 = R0;
    F6 = DM(M2, I3);
    R0 = R0 - 1;
    IF LT R0 = R0 + 1;
    DM(S_MG, I6) = R0;
    M2 = R0;
    F7 = DM(M2, I3);
    F7 = F7 - F6;
    F7 = F7 * F1;
    R0 = I6;                            // the tone stack's coefficients and state, circular:
    R1 = S_EQC;                         // 4 bands x {b0, b1, b2, -a1, -a2} and x {s1, s2}
    R1 = R0 + R1;
    B8 = R1;
    L8 = 20;
    R1 = S_EQS;
    R1 = R0 + R1;
    B4 = R1;
    L4 = 8;
    I11 = B11;
    F4 = PM(I8, M9);                    // b0 of band 0
    LCNTR = 16, DO n_eqx UNTIL LCE;
      F8 = PM(0, I11);
      F0 = F8 * F2;                     // the model x its gain
      R5 = PASS R5;
      IF EQ JUMP n_notail;
      F8 = DM(I5, M1);                  // + HIST backwards x the tail's gain
      F8 = F8 * F6;
      F0 = F0 + F8;
n_notail:
      DM(I0, M0) = F0;                  // into HIST; then the four bands (transposed direct
      // form II: y = b0 x + s1, s1 = b1 x - a1 y + s2, s2 = b2 x - a2 y), x in F0, F1, F0, ...
      F12 = F0 * F4, F4 = PM(I8, M9);
      F9 = F0 * F4, F8 = DM(I4, M0), F4 = PM(I8, M9);
      F10 = F0 * F4, F1 = F8 + F12, F4 = PM(I8, M9);
      F12 = F1 * F4, F4 = PM(I8, M9);
      F14 = F1 * F4, F9 = F9 + F12, F13 = DM(I4, M4);
      F9 = F9 + F13;
      F10 = F10 + F14, DM(-1, I4) = F9;
      DM(I4, M0) = F10, F4 = PM(I8, M9);
      F12 = F1 * F4, F4 = PM(I8, M9);
      F9 = F1 * F4, F8 = DM(I4, M0), F4 = PM(I8, M9);
      F10 = F1 * F4, F0 = F8 + F12, F4 = PM(I8, M9);
      F12 = F0 * F4, F4 = PM(I8, M9);
      F14 = F0 * F4, F9 = F9 + F12, F13 = DM(I4, M4);
      F9 = F9 + F13;
      F10 = F10 + F14, DM(-1, I4) = F9;
      DM(I4, M0) = F10, F4 = PM(I8, M9);
      F12 = F0 * F4, F4 = PM(I8, M9);
      F9 = F0 * F4, F8 = DM(I4, M0), F4 = PM(I8, M9);
      F10 = F0 * F4, F1 = F8 + F12, F4 = PM(I8, M9);
      F12 = F1 * F4, F4 = PM(I8, M9);
      F14 = F1 * F4, F9 = F9 + F12, F13 = DM(I4, M4);
      F9 = F9 + F13;
      F10 = F10 + F14, DM(-1, I4) = F9;
      DM(I4, M0) = F10, F4 = PM(I8, M9);
      F12 = F1 * F4, F4 = PM(I8, M9);
      F9 = F1 * F4, F8 = DM(I4, M0), F4 = PM(I8, M9);
      F10 = F1 * F4, F0 = F8 + F12, F4 = PM(I8, M9);
      F12 = F0 * F4, F4 = PM(I8, M9);
      F14 = F0 * F4, F9 = F9 + F12, F13 = DM(I4, M4);
      F9 = F9 + F13;
      F10 = F10 + F14, DM(-1, I4) = F9;
      DM(I4, M0) = F10, F4 = PM(I8, M9);    // (b0 of band 0 again: the buffers are circular)
      F2 = F2 + F3, PM(I11, M9) = F0;
n_eqx: F6 = F6 + F7;
    L4 = 0;
    L8 = 0;
    R0 = DM(S_G1, I6);
    DM(S_GAIN, I6) = R0;
    R0 = I0;
    R1 = B0;
    R0 = R0 - R1;
    DM(S_HW, I6) = R0;
    R0 = I5;
    R1 = B5;
    R0 = R0 - R1;
    DM(S_MR, I6) = R0;

    // ---- the block's DMA jobs all done (the last write-back ran during the head and the mix)
    R0 = DM(G_JOBS);
    R0 = PASS R0;
    IF EQ JUMP n_back;
    R9 = POLLMAX;
n_ew: CALL pump;
    R0 = DM(J_DONE);
    R1 = NJOBS;
    COMP(R0, R1);
    IF EQ JUMP n_ewd;
    R0 = DM(DMA_FAIL);
    R0 = PASS R0;
    IF NE JUMP n_ewd;
    R0 = DM(REP + R_POLLS);
    R0 = R0 + 1;
    DM(REP + R_POLLS) = R0;
    R9 = R9 - 1;
    IF NE JUMP n_ew;
    CALL dma_abort;
n_ewd:
    R0 = 0;
    DM(DMAC0) = R0;                     // the channel off (its reset value)
    R0 = DM(REP + R_POLLS);
    R1 = DM(REP + R_MAXPOLLS);
    R1 = MAX(R0, R1);
    DM(REP + R_MAXPOLLS) = R1;
    R0 = DM(DMA_FAIL);
    R0 = PASS R0;
    IF NE JUMP m_fail;
    R0 = DM(S_T, I6);                   // samples in the rings since the load
    R1 = 16;
    R0 = R0 + R1;
    R1 = T_MAX;
    R0 = MIN(R0, R1);
    DM(S_T, I6) = R0;
    JUMP n_back;


// ---- a DMA failed or the channel was not free: silence; the slot starts again
// after BACKOFF_N calls of any instance
m_fail:
    R0 = 0;
    DM(S_INIT, I6) = R0;
    R0 = BACKOFF_N;
    DM(REP + R_BACKOFF) = R0;
m_silent:
    R0 = 0;
    I11 = B11;
    LCNTR = 16, DO m_silw UNTIL LCE;
m_silw: PM(I11, M9) = R0;

n_back:
// METER_EXIT
    R0 = DM(SAVE + 1);
    R1 = DM(SAVE + 2);
    R2 = DM(SAVE + 3);
    R3 = DM(SAVE + 4);
    R4 = DM(SAVE + 5);
    R5 = DM(SAVE + 6);
    R6 = DM(SAVE + 7);
    R7 = DM(SAVE + 8);
    R8 = DM(SAVE + 9);
    R9 = DM(SAVE + 10);
    R10 = DM(SAVE + 11);
    R11 = DM(SAVE + 12);
    R12 = DM(SAVE + 13);
    R13 = DM(SAVE + 14);
    R14 = DM(SAVE + 15);
    R15 = DM(SAVE + 16);
    S0 = DM(SAVE + 17);
    S1 = DM(SAVE + 18);
    S2 = DM(SAVE + 19);
    S3 = DM(SAVE + 20);
    S4 = DM(SAVE + 21);
    S5 = DM(SAVE + 22);
    S8 = DM(SAVE + 23);
    S9 = DM(SAVE + 24);
    S10 = DM(SAVE + 25);
    S11 = DM(SAVE + 26);
    S12 = DM(SAVE + 27);
    S13 = DM(SAVE + 28);
    S14 = DM(SAVE + 29);
    L0 = 0; L1 = 0; L2 = 0; L3 = 0; L4 = 0; L5 = 0;
    L8 = 0; L9 = 0; L10 = 0; L11 = 0;
    B0 = DM(SAVE + 30);
    I0 = DM(SAVE + 31);
    B1 = DM(SAVE + 32);
    B2 = DM(SAVE + 33);
    B3 = DM(SAVE + 34);
    I6 = DM(SAVE + 35);
    B4 = DM(SAVE + 36);
    I4 = DM(SAVE + 37);
    B5 = DM(SAVE + 38);
    I5 = DM(SAVE + 39);
    M0 = DM(SAVE + 40);
    M1 = DM(SAVE + 41);
    M2 = DM(SAVE + 42);
    M3 = DM(SAVE + 43);
    M4 = DM(SAVE + 44);
    B8 = DM(SAVE + 45);
    I8 = DM(SAVE + 46);
    B9 = DM(SAVE + 47);
    I9 = DM(SAVE + 48);
    B10 = DM(SAVE + 49);
    I10 = DM(SAVE + 50);
    B11 = DM(SAVE + 51);
    I11 = DM(SAVE + 52);
    M8 = DM(SAVE + 53);
    M9 = DM(SAVE + 54);
    M10 = DM(SAVE + 55);
    M11 = DM(SAVE + 56);
    S6 = DM(SAVE + 57);
    S7 = DM(SAVE + 58);
    M5 = DM(SAVE + 59);
    M6 = DM(SAVE + 60);
    M7 = DM(SAVE + 61);
    I12 = DM(SAVE + 62);
    L12 = DM(SAVE + 63);
    MODE1 = DM(SAVE + 0);
    NOP;
    RTS (LR);

// ---- the DMA jobs: one chain at a time on EP DMA channel 0. pump notices the
// running chain's end (its sentinel) and starts the next job when it is ready
// (EVENTS: +1 when a far layer has its newest tap, +1 when it is computed).
// Uses R0-R3, R6, R8, R10, I0-I3, I5, M4, L1, L2.
pump:
    I5 = DM(J_CHKADR);                  // (early: an I register used just after its load stalls)
    R0 = DM(DMA_FAIL);
    R0 = PASS R0;
    IF NE RTS;
    R0 = DM(J_BUSY);
    R0 = PASS R0;
    IF EQ JUMP p_next;
    R1 = DM(0, I5);
    R0 = DM(J_CHKVAL);
    COMP(R0, R1);
    IF NE RTS;
    R0 = 0;
    DM(J_BUSY) = R0;
    R0 = DM(J_DONE);
    R0 = R0 + 1;
    DM(J_DONE) = R0;
p_next:
    R0 = DM(J_NEXT);
    R1 = NJOBS;
    COMP(R0, R1);
    IF GE RTS;
    R1 = LSHIFT R0 BY 3;
    R2 = JOBS;
    R1 = R1 + R2;
    I5 = R1;
    R3 = DM(EVENTS);
    R2 = DM(J_READY, I5);
    COMP(R3, R2);
    IF LT RTS;
    R0 = R0 + 1;
    DM(J_NEXT) = R0;
    R0 = 1;
    DM(J_BUSY) = R0;
    R0 = DM(J_TYPE, I5);
    R0 = PASS R0;
    IF NE JUMP p_w;
    // a far layer's taps: TCB 3t + c reads tap t (oldest first) of channel c
    I3 = DM(J_ROW, I5);
    I0 = DM(J_CHAIN, I5);
    MODIFY(I0, TCB_EI);
    R8 = DM(G_SDR);
    R1 = DM(T_RB, I3);
    R8 = R8 + R1;                       // channel 0's ring
    M4 = DM(T_LW, I3);
    R2 = DM(M4, I6);                    // this block's write offset
    R10 = DM(T_L, I3);
    R1 = DM(T_KD, I3);
    R2 = R2 + R1;                       // the oldest tap's window
    IF LT R2 = R2 + R10;
    R3 = DM(T_D, I3);
    R6 = DM(T_STRIDE, I3);
    LCNTR = KM1, DO p_rl UNTIL LCE;
      R1 = R8 + R2;
      DM(I0, 6) = R1;
      R1 = R1 + R6;
      DM(I0, 6) = R1;
      R1 = R1 + R6;
      DM(I0, 6) = R1;
      R2 = R2 + R3;
      COMP(R2, R10);
p_rl: IF GE R2 = R2 - R10;
    R1 = DM(G_SDR);                     // the sentinel TCB: MAGIC from SENT into the flag
    R2 = SENT_OFF;
    R1 = R1 + R2;
    DM(0, I0) = R1;
    I0 = DM(J_FLAG, I5);
    R1 = 0;
    DM(0, I0) = R1;
    R1 = I0;
    DM(J_CHKADR) = R1;
    R1 = MAGIC;
    DM(J_CHKVAL) = R1;
    R0 = 0;                             // external -> internal
    JUMP p_go;
p_w:
    // a write-back: each far layer's 16 new words per channel, then the sequence number
    L1 = 0;
    L2 = 0;
    R1 = DM(J_CHAIN, I5);
    R2 = TCB_EI;
    R1 = R1 + R2;
    I0 = R1;
    I1 = DM(J_ROW, I5);                 // (FARTAB + the group's first far layer)
    I2 = DM(J_FLAG, I5);                // (WADDR + the same)
    R2 = DM(J_N, I5);
    LCNTR = R2, DO p_wl UNTIL LCE;
      R1 = DM(I1, 1);
      I3 = R1;
      R6 = DM(T_STRIDE, I3);
      R1 = DM(I2, 1);
      DM(I0, 6) = R1;
      R1 = R1 + R6;
      DM(I0, 6) = R1;
      R1 = R1 + R6;
p_wl: DM(I0, 6) = R1;
    R1 = DM(G_SDR);
    R2 = SENT2_OFF;
    R1 = R1 + R2;
    DM(0, I0) = R1;
    DM(J_CHKADR) = R1;
    R1 = I6;
    R2 = S_SEQ;
    R1 = R1 + R2;
    DM(3, I0) = R1;                     // (TCB_II - TCB_EI)
    R1 = DM(S_SEQ, I6);
    R1 = R1 + 1;
    DM(S_SEQ, I6) = R1;
    DM(J_CHKVAL) = R1;
    R0 = TRAN;                          // internal -> external
p_go:
    R1 = DFLSH;                         // HRM: flush, clear CP, enable with CHEN, then CP
    DM(DMAC0) = R1;                     // starts the chain
    R1 = 0;
    DM(CPEP0) = R1;
    R1 = DEN_CHEN;
    R1 = R1 OR R0;
    DM(DMAC0) = R1;
    R1 = DM(J_CP, I5);
    DM(CPEP0) = R1;
    RTS;

// Wait (bounded) for this far layer's taps (job J_DONE > T_RPOS).
fwait:
    R9 = POLLMAX;
fw_l: CALL pump;
    R0 = DM(J_DONE);
    R1 = DM(T_RPOS, I4);
    COMP(R0, R1);
    IF GT RTS;
    R0 = DM(DMA_FAIL);
    R0 = PASS R0;
    IF NE RTS;
    R0 = DM(REP + R_POLLS);
    R0 = R0 + 1;
    DM(REP + R_POLLS) = R0;
    R9 = R9 - 1;
    IF NE JUMP fw_l;
    JUMP dma_abort;

// A far layer has its taps: the newest (this block's x) into the staging buffer
// and the write-back buffer; the windows from before the load to the silence
// state; the mirror when the write offset is 0; then the next job may start.
fcopy:
    R3 = DM(T_SB, I4);
    R1 = 80;                            // tap K-1 of channel 0
    R3 = R3 + R1;
    I0 = R3;
    I8 = DM(T_OB, I4);                  // and the write-back buffer (through PM)
    I12 = X;                            // X read through PM: X shares Block 2 with this code
    BIT SET MODE1 PEYEN;                // two words a move (M7 = M10 = 2)
    NOP;
    LCNTR = 3, DO fc_c UNTIL LCE;
      LCNTR = 8, DO fc_l UNTIL LCE;
        F0 = PM(I12, M10);
fc_l:   DM(I0, M7) = F0, PM(I8, M10) = F0;
      MODIFY(I0, 80);
fc_c: NOP;
    BIT CLR MODE1 PEYEN;
    NOP;
    M4 = DM(T_LW, I4);                  // where the write-back goes
    R2 = DM(M4, I6);
    I5 = DM(T_WA, I4);
    R8 = DM(G_SDR);
    R1 = DM(T_RB, I4);
    R8 = R8 + R1;
    R1 = R8 + R2;
    DM(0, I5) = R1;
    R2 = PASS R2;
    IF NE JUMP fc_nomir;
    R1 = DM(T_L, I4);                   // the mirror of the ring's first 16 words
    R1 = R1 + R8;
    R6 = DM(T_STRIDE, I4);
    I3 = X;
    LCNTR = 3, DO fc_mc UNTIL LCE;
      I0 = R1;
      LCNTR = 16, DO fc_mw UNTIL LCE;
        F0 = DM(I3, 1);
fc_mw:  DM(I0, 1) = F0;
      R1 = R1 + R6;
fc_mc: NOP;
fc_nomir:
    R0 = DM(S_T, I6);                   // windows from before the load: the silence state
    R1 = DM(T_KD, I4);
    R1 = R0 + R1;
    IF GE JUMP fc_nopatch;
    R11 = DM(T_D, I4);
    R3 = DM(T_SB, I4);
    R2 = DM(T_SIL, I4);
    R6 = I6;
    R2 = R2 + R6;
    I5 = R2;
    F6 = 16.0;
    F8 = DM(0, I5);
    F8 = F8 * F6;
    F9 = DM(1, I5);
    F9 = F9 * F6;
    F10 = DM(2, I5);
    F10 = F10 * F6;
    LCNTR = KM1, DO fp_t UNTIL LCE;
      R2 = -R1;                         // the window's samples before the load
      R6 = 16;
      R2 = MIN(R2, R6);
      R2 = PASS R2;
      IF LE JUMP fp_skip;
      I0 = R3;
      LCNTR = R2, DO fp_0 UNTIL LCE;
fp_0:   DM(I0, 1) = F8;
      R6 = 96;
      R6 = R6 + R3;
      I0 = R6;
      LCNTR = R2, DO fp_1 UNTIL LCE;
fp_1:   DM(I0, 1) = F9;
      R6 = 192;
      R6 = R6 + R3;
      I0 = R6;
      LCNTR = R2, DO fp_2 UNTIL LCE;
fp_2:   DM(I0, 1) = F10;
fp_skip:
      R6 = 16;
      R3 = R3 + R6;
fp_t: R1 = R1 + R11;
fc_nopatch:
    R0 = DM(EVENTS);
    R0 = R0 + 1;
    DM(EVENTS) = R0;
    CALL pump;
    RTS;

// The 16 words at I3 (DM, step M0 = 1) into the ring B8 (L8 = its length,
// already set) from offset M8, then its guard (B8 + M11, M11 = the length) =
// its first word.
n_put:
    MODIFY(I8, M8);
    F0 = DM(I3, M0);
    LCNTR = 16, DO n_putw UNTIL LCE;
n_putw: F0 = DM(I3, M0), PM(I8, M9) = F0;
    I8 = B8;                            // (before L8's save: I8 then is not used just after its load)
    R1 = L8;
    L8 = 0;
    F0 = PM(0, I8);
    PM(M11, I8) = F0;
    L8 = R1;
    RTS;

// ---- cold code: a slot's start and a model's load only, in Block 3 (COLD_PM, the top
// of the module's region), so that Block 2 keeps X, HS and IN beside the hot code: the
// pair loop then reads them without DM/PM block conflicts against the weights in Block 3.
.section pm COLD_PM

// ---- a slot's first call (and after a failure): its state, sentinels, HIST
m_init:
    R0 = 0;
    DM(S_SIG, I6) = R0;                 // no model loaded: the next block loads one
    DM(P_SIGN, I0) = R0;
    DM(S_GAIN, I6) = R0;
    DM(S_G1, I6) = R0;
    DM(S_MG, I6) = R0;
    DM(S_MR, I6) = R0;
    DM(S_HW, I6) = R0;
    DM(S_SEQ, I6) = R0;
    DM(S_T, I6) = R0;
    DM(S_HHW, I6) = R0;
    R1 = 1;
    DM(S_FRESH, I6) = R1;               // no tail: nothing played before
    DM(S_EQDIRTY, I6) = R1;             // read the tone knobs
    R0 = I6;
    R1 = S_EQIDX;
    R1 = R1 + R0;
    I5 = R1;
    R1 = -1;
    LCNTR = 4, DO mi_eqi UNTIL LCE;
mi_eqi: DM(I5, 1) = R1;                 // (S_EQC follows S_EQIDX)
    F1 = 1.0;
    R2 = 0;
    LCNTR = 4, DO mi_eqc UNTIL LCE;     // flat until the knobs are read
      DM(I5, 1) = F1;
      DM(I5, 1) = R2;
      DM(I5, 1) = R2;
      DM(I5, 1) = R2;
mi_eqc: DM(I5, 1) = R2;
    LCNTR = 8, DO mi_eqs UNTIL LCE;     // (S_EQS follows S_EQC)
mi_eqs: DM(I5, 1) = R2;
    R0 = DM(G_SDR);
    R1 = SENT_OFF;
    R1 = R1 + R0;
    I5 = R1;
    R1 = MAGIC;
    DM(0, I5) = R1;                     // what a read chain's sentinel TCB copies
    DM(1, I5) = R2;                     // where a write chain's sentinel TCB writes (SENT2)
    R1 = HIST_OFF;
    R1 = R1 + R0;
    I5 = R1;
    LCNTR = 512, DO mi_hist UNTIL LCE;
mi_hist: DM(I5, 1) = R2;
    R0 = 1;
    DM(S_INIT, I6) = R0;
    RTS;

// A crossfade starts: the tail from the last output (17 steps; none on a fresh
// slot), the model silent until it has loaded.
n_cut:
    R0 = 17;
    R1 = DM(S_FRESH, I6);
    R1 = PASS R1;
    IF NE R0 = R0 - R0;
    DM(S_MG, I6) = R0;
    R0 = DM(S_HW, I6);
    R0 = R0 - 1;
    R2 = 512;
    IF LT R0 = R0 + R2;
    DM(S_MR, I6) = R0;
    R0 = 0;
    DM(S_GAIN, I6) = R0;
    DM(S_FRESH, I6) = R0;
    RTS;

// ---- load the model at R8 (an IR slot's top word): N_STREAM words, top-down,
// x the scale, into the slot's stream, by DMA in LBUF_N-word chunks; then the
// slot's rings to the silence state. DMA_FAIL = 1 when a chunk did not arrive.
ld_model:
    R0 = 0;
    DM(DMA_FAIL) = R0;
    R0 = DM(REP + R_LOADS);
    R0 = R0 + 1;
    DM(REP + R_LOADS) = R0;
    I3 = R8;
    F0 = DM(-5, I3);                    // its input trim from the next block on: word 5,
    F1 = DM(STOMP_GAIN);                // 10^(-input_level_dbu/20) (0: none), x the
    F0 = F0 * F1;                       // Stomp's level
    DM(S_TRIM, I6) = F0;
    F3 = DM(-3, I3);                    // the scale, 2^e
    R0 = DM(G_SDR);
    R1 = SENT_OFF;
    R0 = R0 + R1;
    DM(LCH + 6 + TCB_EI) = R0;          // the sentinel TCB reads MAGIC from SENT
    R11 = 0;                            // stream words done
    R0 = I6;
    R1 = S_STREAM;
    R0 = R0 + R1;
    I4 = R0;                            // where they go
ld_chunk:
    R0 = N_STREAM;
    R0 = R0 - R11;
    R1 = LBUF_N;
    R0 = MIN(R0, R1);                   // n words this chunk
    R10 = R0;
    DM(LCH + TCB_IC) = R0;
    R1 = R8;                            // from top - 8 - (done + n - 1), upwards
    R2 = 7;
    R1 = R1 - R2;
    R1 = R1 - R11;
    R1 = R1 - R0;
    DM(LCH + TCB_EI) = R1;
    R0 = 0;
    DM(FLAGL) = R0;
    R1 = DFLSH;
    DM(DMAC0) = R1;
    DM(CPEP0) = R0;
    R1 = DEN_CHEN;
    DM(DMAC0) = R1;
    R1 = LCH_CP;
    DM(CPEP0) = R1;
    R9 = LPOLLMAX;
ld_w: R0 = DM(FLAGL);
    R1 = MAGIC;
    COMP(R0, R1);
    IF EQ JUMP ld_got;
    R9 = R9 - 1;
    IF NE JUMP ld_w;
    CALL dma_abort;
    RTS;
ld_got:
    R0 = LBUF - 1;                      // the chunk is the stream reversed: copy it back
    R0 = R0 + R10;
    I5 = R0;
    M2 = -1;
    LCNTR = R10, DO ld_cp UNTIL LCE;
      F0 = DM(I5, M2);
      F0 = F0 * F3;
ld_cp: DM(I4, 1) = F0;
    R11 = R11 + R10;
    R0 = N_STREAM;
    COMP(R11, R0);
    IF LT JUMP ld_chunk;
    R0 = 0;
    DM(DMAC0) = R0;
    // the slot's rings to the silence state; the far rings are patched as read
    I4 = CLR;
    R11 = I6;
    R3 = S_STREAM + ST_SIL;
    R3 = R3 + R11;
    F5 = 16.0;                          // (the values are kept / 16: HX Edit's +-15.8)
    LCNTR = NCLR, DO ld_clr UNTIL LCE;
      R1 = DM(0, I4);
      R1 = R1 + R11;
      I3 = R1;
      R1 = DM(2, I4);
      R1 = R1 + R3;
      I5 = R1;
      F0 = DM(0, I5);
      F0 = F0 * F5;
      R1 = DM(1, I4);
      LCNTR = R1, DO ld_clrw UNTIL LCE;
ld_clrw: DM(I3, 1) = R0;
      NOP;
ld_clr: MODIFY(I4, 3);
    R0 = 0;                             // every ring from offset 0; no samples yet
    DM(S_T, I6) = R0;
    DM(S_HHW, I6) = R0;
    R1 = I6;
    R2 = S_LW;
    R1 = R1 + R2;
    I5 = R1;
    LCNTR = NLAYERS, DO ld_lw UNTIL LCE;
ld_lw: DM(I5, 1) = R0;
    RTS;

// A chain that did not end: off as HRM p. 3-124 says (DEN off, wait for EXTS,
// count 0), and the block fails.
dma_abort:
    R0 = 1;
    DM(DMA_FAIL) = R0;
    R0 = DM(DMAC0);
    DM(REP + R_DMAC) = R0;
    R0 = DM(ICEP0);
    DM(REP + R_ICEP) = R0;
    R0 = 0;
    DM(DMAC0) = R0;
    R2 = 100;
da_w: R0 = DM(DMAC0);
    R1 = EXTSM;
    R0 = R0 AND R1;
    IF EQ JUMP da_ok;
    R2 = R2 - 1;
    IF NE JUMP da_w;
da_ok:
    R0 = 0;
    DM(ICEP0) = R0;
    DM(CPEP0) = R0;
    R0 = DM(REP + R_TIMEOUTS);
    R0 = R0 + 1;
    DM(REP + R_TIMEOUTS) = R0;
    RTS;

// (no model, pass-through, no SDRAM block: rare paths)
n_none:
    R0 = DM(S_SIG, I6);                 // no model in that slot: silence (after the tail)
    R0 = PASS R0;
    IF EQ JUMP n_zero;
    CALL n_cut;
    R0 = 0;
    DM(S_SIG, I6) = R0;
n_zero:                                 // no model this block: the tail alone
    R0 = 0;
    DM(S_G1, I6) = R0;
    DM(P_SIGN, I0) = R0;                // the next call checks the model
    I11 = B11;
    LCNTR = 16, DO n_ldz UNTIL LCE;
n_ldz: PM(I11, M9) = R0;
    JUMP n_mix;

// ---- the block passes its input through (no slot)
m_pass:
    LCNTR = 16, DO m_passw UNTIL LCE;
      R0 = DM(I1, 1);
m_passw: DM(I2, 1) = R0;
    JUMP n_back;

// ---- no SDRAM block of the size it needs (the build did not raise the budget)
m_nosdr:
    R0 = DM(REP + R_NOSDR);
    R0 = R0 + 1;
    DM(REP + R_NOSDR) = R0;
    JUMP m_pass;
