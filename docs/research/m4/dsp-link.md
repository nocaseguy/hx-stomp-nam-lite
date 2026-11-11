# The M4 to DSP link [verified on unit]

The SPI frames between the SHARC and the M4, and how the DSP sends its own values in a frame's tail. Status tags as in [conventions.md](../conventions.md).

- Framed 1 KB (256-word) SPI/DMA frames. Word 0 is magic `0xFACEF00D`, word 255 is trailer `0xD00FECAF`, payload from word 2.
- The M4 receive callback is reached through a literal at `0x28da6134` (stock value `0x10001095`; `r1` = RX buffer). Hooking it by replacing the literal and tail-calling the stock address works.
- The M4 sees halfword-swapped words: `ror #16` to read them.
- Most frames are empty. Words ~70..254 are unused filler.
- **The DSP can send data to the M4 by writing into the frame tail.** A SHARC routine scanned DSP memory (internal `0x80000..0x100000`, DDR2 `0x200000..0x330000`, 256 words per call) for `0xFACEF00D` with `0xD00FECAF` at +255, wrote `0x600DF00D` at word 200, a tag at 201 and a call counter at 202, and all three arrived at the M4. Word 203 onward is free. This is the transport for DSP-measured values (for example gain reduction), and it needs no knowledge of Line 6's own message formats.
- Searching Line 6's existing message traffic for a meter value ("needle in a haystack") was tried and abandoned.

Frame words the GR meter uses (200..253): [features/gr-meter.md](../features/gr-meter.md).
