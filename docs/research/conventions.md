# Conventions

How the research notes are written and where a new finding goes. Start from [INDEX.md](INDEX.md) to find the note you need.

## Status tags

Every claim carries a status:

- **[verified on unit]**: seen working on a real HX Stomp.
- **[verified offline]**: checked in the simulator, by disassembly, or by a checksum, not on a unit.
- **[hypothesis]**: reasoned, not yet checked. Treat with suspicion.

No Line 6 code or data is in this repository. Addresses in these notes are facts about the stock 3.80.0 file you supply yourself (`HX_Stomp_v3.80.0_0x103966115.hxf`, MD5 `a2cd8f4ae56f49415380270ebc484bf1`, gitignored). Every patch asserts the stock bytes it replaces before writing.

Write "HX Stomp" in full, never "Stomp" or "the HX".

## Where to add a new finding

- Find the note in [INDEX.md](INDEX.md) that covers that part of the system (a setting → `m4/settings.md`, a compressor core → `sharc/cores/compressors.md`) and add the fact there, under the matching heading. If no note fits, start one in the matching folder and add a line for it to `INDEX.md`, with its "read this when" hint.
- Facts and history live apart. A reference note says what is true, with its status tag and how it was found. The trial and error that led there (image X, MD5 Y, result Z) goes in the feature's own note, or its `-log.md` when it grows long, and the reference note links to it.
- Link rather than copy: a feature note links to the system notes it depends on.

- Add facts under the matching section, with a status tag and, for addresses, how you found them (disassembly, simulator, unit).
- When a hypothesis is confirmed or refuted, edit it in place and say how.
- Keep entries short. Put long dumps in a scratch file, not here.
- Never paste Line 6 code or data here; describe it and give addresses.

## Goal and working method

Goal: a completely custom firmware for the HX Stomp, built in small steps, each verifiable on the real unit.

- The repo is a **binary patcher**: `build.py` reads the user's stock `.hxf` and writes `build/HX_Stomp_v3.80.0_HXtra.hxf`.
- Test on the unit by running the image from RAM (nothing is written to the Stomp; power-cycle restores the installed firmware). See [RAM_RUN.md](../../RAM_RUN.md).
- **A RAM run keeps the application's eMMC writes in SDRAM** (`hxf_ram.py run` prints `writes: ram`, the default): Global Settings, presets and IRs changed during the run are gone at power-off, so a value set in a RAM run never reaches the next boot. To test anything that must survive a power-cycle (a setting's persistence), run with `hxf_ram.py run <build> --stock <stock .hxf> --writes pass`: writes outside the firmware overlay then go to the real eMMC (they change the unit's real settings), while the firmware itself still runs from RAM. `hxboot` has no flag for it; run its steps by hand with `--writes pass` on the last one.
- **Always build to `build/HX_Stomp_v3.80.0_HXtra.hxf`.** Earlier "freezes" were the user running a stale, differently named file. Tell the user the MD5 of what you built.
- The user hates repeated manual readings ("I cannot be providing reading after reading after reading"). Prefer making unknowns **runtime parameters** (Global Settings knobs) so one image can test several hypotheses.
- Do not install anything on the user's machine. Do not commit or push unless told. Do not add attribution lines to commits.
- **`[!] the loader could not start the eMMC (status 0x10b): not checked` is harmless** [verified on unit]: every `hxboot` prints it, and the run still starts and reads presets normally. It means only that the loader skipped its own comparison of the eMMC with the stock file.
- **Killing an `hx_ctl.py` session in the middle of a preset sweep leaves the front panel stuck** [verified on unit, 2026-11-11]: the Edit view's knob stops moving between blocks and every preset shows the same blocks, while USB still answers; a power-cycle clears it. Let a sweep finish, or close its session.

Environment notes: macOS with zsh. `sed -i` needs a backup suffix on macOS, so edit with Python. Do not `echo ======` in zsh.
