@ metronome.s - the Metronome block in the signal flow: Volume/Pan's teal pictures, with on/off, instead of Looper's grey ones.
.syntax unified
.thumb
.equ PRESET_ID, 181                 @ tools/patch_click.py PRESET_ID
.equ TEAL, 0x10                     @ Volume/Pan's browser category

metronome_slot:                     @ at 0x28dd3042, for ldrb.w r2, [sp, #0x10]: the block info at sp+4 has its preset model ID at +1
    ldrb.w r2, [sp, #0x10]
    ldrb.w r12, [sp, #6]            @ flags and r12 are free at the site
    cmp r12, #0
    bne 1f
    ldrb.w r12, [sp, #5]
    cmp r12, #PRESET_ID
    it eq
    moveq r2, #TEAL
1:  bx lr
