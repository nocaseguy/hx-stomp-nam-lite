#!/usr/bin/env python3
"""usb_commands.py - the HX Edit editor-service commands HXtra adds, one line per command number.

HX Edit's editor service (service 6) runs a command by its number, 0..0x7b, from a table the boot fills (0x28e165f0; see
docs/research/m4/usb-editor.md). Stock 3.80 registers 110 of them; FREE are the rest. A feature claims a free number by putting its
name on the number's line, so two branches claiming the same number edit the same line and the merge conflicts; tests/test_hxtra.py
fails on a duplicate, on a number stock uses, and on a line naming no feature. The feature's M4 code gets the number from
usb.inc (inc()), so it is written down here only.
"""

REGISTER = 0x28e165f0               # (command, &{handler, check, 0}): every stock registration calls it, from a stub
COUNT = 0x7c                        # it refuses higher numbers
FREE = (0x13, 0x1d, 0x1f, 0x20, 0x26, 0x2c, 0x36, 0x37, 0x4f, 0x50, 0x51, 0x52, 0x64, 0x65)   # registered by no stock stub

COMMANDS = (   # (command, the feature using it or None, what it does)
    (0x52, 'screen_mirror', 'the frame on the LCD, run-length coded (src/m4/screen_mirror.s)'),
)


def by_feature():
    """feature -> its command."""
    return {name: cmd for cmd, name, _ in COMMANDS if name}


def inc(feature):
    """usb.inc for a feature's M4 code: its command as CMD."""
    return f'.equ CMD, {by_feature()[feature]:#x}\n'


def registered(read, branch_target):
    """The commands the firmware read(va, n) registers: the movs r0, #command before each call of REGISTER."""
    found = []
    for at in range(REGISTER - 0x8000, REGISTER + 0x10000, 2):
        hw = read(at, 4)
        if hw[1] & 0xf8 == 0xf0 and hw[3] & 0xd0 == 0xd0 and branch_target(at, hw) == REGISTER:
            found.append(next(read(at - b, 2)[0] for b in range(2, 14, 2) if read(at - b, 2)[1] == 0x20))
    return found
