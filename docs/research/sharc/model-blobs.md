# Model blobs and parameter maps

What a model is made of: its parameters in Entry 3, its blob's node tree and parameter map in Entry 4, and its row in Entry 0; adding a parameter; tempo sync. Status tags as in [conventions.md](../conventions.md).

## Model parameters (Entry 3, Entry 4 parameter map, Entry 0 info row) [verified offline]

- A model's parameter count has to agree in three places: Entry 3's descriptor (`d[7]` parameters, `d[6]` states), the blob's parameter map (one input node and one slot-map entry per parameter), and the Entry 0 UI Model Info Table row (bytes 24..35, three counts).
- Parameter map header: offsets of tables A (nodes), B, C (edges), D (slot map), E and F at words 0, 2, .. 10; sizes at 12..17; counts nA..nF at 18..23. The sizes follow the tables in every map checked: sum of node state words, nA, nD + sum n_out + inputs, nC + nD + inputs, nD, nE.
- Deluxe Comp (blob 68 mono, 349 stereo): seven input nodes, op `0xa` float or `0xb` int (Ratio). Slot map {node, state index, slot, 0}; state index = the input's rank in node order, matching Entry 3's state records `{0, 0x80b98, name, type, index}`. Root init records `{path [1, 0], slot, value, kind 1}` give each slot's default.
- `tools/patch_comp.py` adds GR Position, GR Direction and GR Thickness (int lists, slots 8..10) to both Deluxe Comps. The new input nodes have no edges, so the DSP is unchanged. Entry 3's tail string section grows in place, and the model table and everything after it move down. The blob's map, init records and relocation list are rebuilt after the node tree.

## The node tree

- **A model blob's node tree overrides member primitives** [verified offline, and on unit by the Kinky-knobs and Kinky-2710 images in the [GR meter log](../features/gr-meter-log.md)]: entries `{slot, type, child_off, child_cnt}` after the root, `type` `0xffffffff` for none; slot k is path [k], member k − 1. The Kinky Comp's core (slot 14; stereo 23 and 33) is **`0x2710`** there, not blob 0's `0x2719`; slot 9 is `0x2711`. The LA Studio Comp overrides slot 13 to `0x239e` only. `0x2710` (registry `0x200180`) shares the process code `0x8d342` with `0x2719` but has its own control function `0x60cf8e`; the Sweep Echo delay (composites `0x6000d4`, `0x600024`) uses it too. The LA Studio Comp and the Red Squeeze share composites (`0x6000ca` mono, `0x60001d` stereo).

## Tempo sync in a parameter map [verified offline]

- Stock Simple Delay (blob 50) gets its delay time from the tempo inside its parameter map, with no M4 code of its own. Its Time knob comes as three Entry 3 parameters: the float `Time` (slot 1; meta `sync` 1, `coupledIndex` 10, `toggleSelectIndex` 11), the int note list `SyncSelect1` (slot 10, values 1..19 = 1/1 .. 1/64 Triplet, 6 = 1/4; meta `persistent` note) and the bool `TempoSync1` (slot 11). Entry 0's Table 2 row counts them (4, 6, 6): the last two are hidden, as `displayParamCount` 4 says.
- The map: `TempoSync1` into a node of op `0x2a` (4 state words, data 0, 0) at port 0, `SyncSelect1` at port 2 (port 1 is free on delays); `Time` into a node of op `0x54` (9 state words, data min, max = 0.00035, 8.0) at port 0, the `0x2a` node at port 1; then op `0x2d` (data 0, 0.00035) and a writer to the delay member's pid 1. Edges are `{src, dst, src port, dst port}`. 344 stock `0x2a` nodes all have data (0, 0); `0x54` follows each in the delays with that model's time range.
- **[hypothesis]**, borne out by the Metronome working on the unit: `0x2a` gives the note's length in seconds at the current tempo while `TempoSync1` is on, and `0x54` takes that or the free `Time`, clamped. `0x2d`'s job is not known (its second word is the clamp's minimum in the delays).
