# Container formats

The `.hxf` file, its L6IA archive and what each entry holds. Status tags as in [conventions.md](../conventions.md).

- `.hxf` wraps an **L6IA archive** of 15 entries (`tools/l6ia.py`, `tools/hxf.py`). `tools/l6ia_verify.py` checks every checksum; a build must print `ALL OK`.
- **Entry 0**: the Cortex-M4 application (LPC4350). Segment 6 is code at `0x28d8fa80` in SDRAM and is writable at runtime. Patches append "caves" to segment 6 and reach them with `b.w` hooks or `ldr.w pc,[pc,#0]` tail-jumps. The file stores words halfword-swapped; `patch_amp.get_entry_swapped` and `_e0_vaddr_to_foff` handle that.
- **Entry 2**: the SHARC (ADSP-2156x) DSP boot stream, LDR blocks. Tag 5 = 48-bit instructions, tag 4 = 32-bit data.
- **Entry 3**: the model table (29 models; metadata such as `gainReductionMeterCount`).
- **Entry 4**: DSP graph blobs. Blob 0 is the composite library (each effect is a composite of primitives). The graph surgery format is only partly understood.
- Internal CRCs must be fixed after editing Entry 0 (`l6ia.fix_internal_crcs`).
- **An Entry 3 too large makes the unit drop every amp and preamp** [verified on unit, 2026-11-11]: every preset with an amp or preamp block loads with 0 blocks (46 of 46 on the dev unit; the other 44 load), and an amp placed alone into an empty preset over USB is dropped too. Bisected with `hx_ctl.py` preset sweeps: Entry 3 at `0xf0d00` bytes (the default build) loads amps; the same Entry 3 zero-padded to `0xf3888` does not, so it is the size, not the contents. The limit lies between `0xf10f0` (below) and `0xf3888`; no constant in that range is in the M4 code. `HX_GR`'s knobs grew it to `0xf3888` (on main too, before `gr-with-nam`); `patch_comp.py` now puts the string section back in the stock tables' dead place at `0x200`, which brings a GR build to `0xd9c88`; amp presets load again on the unit (image `efc35f01…`, `HX_GR=1 HX_CLICK=1 HX_DSP_METER=1`, 2026-11-11). An `HX_CLICK=1` build (no GR) is at `0xf10f0` and loads amps and preamps, and amps can be added [verified on unit, 2026-11-11, image `33ac5cc3…`: main with `HX_TUNER HX_BPM HX_BREATHING_LINE HX_DSP_METER HX_LONG_PRESS HX_MORE_SNAPSHOTS HX_CLICK`, RAM run], so the limit lies between `0xf10f0` and `0xf3888`.

Entries 7 and 8 (the image store) are in [image-store.md](image-store.md).
