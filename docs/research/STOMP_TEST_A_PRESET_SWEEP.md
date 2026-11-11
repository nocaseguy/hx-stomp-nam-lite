# Test A: factory-preset sweep against NAM's memory (HX Stomp, 2026-11-04)

Question: does any stock preset leave something running that writes into NAM's memory
(the failure that made NAM A2 Full crackle: CM Crunch & co. left an object writing 1..42 words
into Full's borrowed rings)? A symptom test on the shipped bytes, no probe build.

Image: `build/HX_Stomp_v3.80.0_NAM_A2_Lite_EQ.hxf` (the 10-knob EQ build, file MD5 e6431a5f),
run from RAM on the owner's HX Stomp. Script: `research/stomp_test_a/sweep.py` (hx_smoke helpers).

Method, per preset i of the unit's 126 (setlist 0), forward then reverse, RAM reboot every 12:
select i, 2 s (its blocks run), write one preset with NAM alone in slot 0 (Model 4, other knobs
0.5, defaults) and the input block on USB 5/6 with nothing playing (digital zero), 1.5 s, record
3 s of USB 1/2. NAM from zero input outputs a constant (its bias: mean 2.4369e-4, -72.3 dBFS);
corrupted weights, rings, tables or code would move it or add noise. Flag: spread > 1e-6,
mean off the fresh-boot baseline by > 1e-6, peak deviation > 1e-5, not loaded, unit not answering.

| run | presets | flagged | max spread (sd) | max peak deviation | mean span |
|---|---|---|---|---|---|
| forward 0..125 | 126 | 0 | 1.67e-9 | 1.64e-8 | 4.5e-10 |
| reverse 125..0 | 126 | 0 | 1.56e-9 | 1.63e-8 | 2.8e-10 |

All loaded, unit answering after each. (The 4-knob build, dcb425f1: 25 presets forward, all clean,
then stopped for the EQ build: `knob4_fwd_partial.jsonl`.)

What this covers: a stock object left running by one preset, beside one NAM block, with NAM's
memory read every call (Block 2/3 code, tables, slot weights and rings; the DDR2 tone table only
when a knob moves, which this test does not do after the preset change).
Not covered: two or three NAM blocks, stock blocks beside NAM, knob moves after the preset change
(re-reads the DDR2 table), HX Edit drags, a long run, other setlists' presets, and writes into
memory NAM does not read every call. Test B (canary probe) is the cause-level check.
Gotcha: macOS gives 0 audio frames while the screen is locked (the first reverse attempt).

## Pass 2 (2026-11-04): three NAMs, a stock block beside them, knobs moved

`research/stomp_test_a/sweep2.py`, same image (e6431a5f) from RAM. Per preset: select, 2 s; then
T1 = NAM, NAM, stock EQ (pid 135), NAM on path A (~8,580 of the 9,000 budget with the empty-preset
base), default knobs, input USB 5/6 silent: record 3 s; T2 = the same with Treble 0.8, Bass 0.3,
Mid 0.7, Mid Freq 1200, Q 1, High Cut 0.6 on all three NAMs (the kernel re-reads its DDR2 tone
table): record 3 s. RAM reboot every 7 presets, fresh-boot baselines for T1 and T2 each boot.

The stock EQ in the chain gives a small noise floor at fresh boot too (T1 sd ~4e-7, T2 ~5e-6),
likely its anti-denormal noise amplified by the NAMs after it, so spread/peak are judged against
the baselines' own noise (3x sd, 4x peak); the steady level against the baseline to 1e-8.

| run | presets | T1 max |level - base| | T2 max |level - base| | flagged |
|---|---|---|---|---|
| forward | 126 | 3.0e-10 | 1.0e-9 | 0 |
| reverse | 126 | 4.1e-10 | 1.0e-9 | 0 (see below) |

Reverse stopped once after preset 89 (Natural AC 2): one hx_ctl status reply timed out (5 s).
Its audio was clean on T1 and T2, the unit answered seconds later with the T2 preset in place;
resumed from preset 88 with the status check retried 3 times (8 s). Not a hang.

Still not covered: HX Edit drags, a long run, other setlists, writes into memory NAM does not read
every call (Test B, the canary probe).
