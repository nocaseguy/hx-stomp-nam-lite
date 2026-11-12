# HX Edit's editor service on the M4

The commands HX Edit sends on its editor stream (service 6) and how the firmware answers them. The host side, transport and message framing are in `tools/hx_ctl.py`'s docstring. Status tags as in [conventions.md](../conventions.md).

## The command table [verified offline, disassembly]

- At boot, `0x28d96adc` calls `0x28e1661c`, which calls one small stub per command. Each stub calls **`0x28e165f0(command, &{handler, check, 0})`**: it refuses a command above `0x7b` and copies the 12 bytes into a table of 20-byte rows at `0x2844ea2c` (`{u8 command, pad, handler, check, 0}`), row = command.
- 110 of the 124 numbers are registered. **Free in stock 3.80: `0x13`, `0x1d`, `0x1f`, `0x20`, `0x26`, `0x2c`, `0x36`, `0x37`, `0x4f`..`0x52`, `0x64`, `0x65`**. Claim one on its line in `tools/usb_commands.py`, the ledger (`tests/test_hxtra.py` fails on a duplicate or a number stock uses, and checks its free list against the stock file); the [screen mirror](../features/screen-mirror.md) has `0x52`.
- `check` validates the parameters; `0x28e19205` (`movs r0, #0; bx lr`) is the one for commands without parameters. Get edit buffer (`0x16`) is registered by the stub at `0x28e1e430` with handler `0x28e1c55d` and that check.

## A handler [verified offline, disassembly]

- `handler(stream, request)`: `[request + 0xc]` is the request's seq (u16). The stream is an object whose word 0 is a vtable: `[vtable + 4]` = `write(stream, bytes, n)` (negative on error), `[vtable + 0xc]` = `finish(stream, 0)`, which ends the message; `[stream + 0x500]` is the service number. `stream - 8` is the stream's lock (`0x28e24c00` lock, `0x28e24bb0` unlock), held around a reply's writes.
- A reply is built from four per-service getters, each called with the service (6): `0x28e157c8` the reply writer `{context, write(context, bytes, n)}`, `0x28e157ec` the word counting the bytes it holds, `0x28e15810` those bytes (0x64 of them), `0x28e15834` empties them. `0x28e15878(writer, seq, status)` writes the reply map's head: `0x83`, `0x66`, `0xcd` + seq (big-endian), `0x67`, status, `0x68`. The handler then writes the result's MessagePack (Get edit buffer: a str8/16/32 head, `0xda`/`0xdb`, then the blob).
- Then, holding the lock: `write(stream, {u16 0, u16 service, u32 length}, 8)` with length = the writer's bytes + the result's, `write` the writer's bytes, `write` the result's bytes, `finish(stream, 0)`. Get edit buffer writes its blob straight from the serializer's buffer as the third write. The generic sender `0x28e15b30` puts the service at offset 2 of the header.
- A result's bytes may go out over several `write` calls: the stream is a byte stream to the host (`hx_ctl.py` reads a message by its header's length).
