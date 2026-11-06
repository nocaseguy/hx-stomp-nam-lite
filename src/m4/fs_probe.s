@ fs_probe.s - a probe for long-press footswitches: for footswitches 1..5, the panel's raw reports and the key events the M4 posts for them,
@ as hex rows at the bottom left of the Home screen, clear of the preset name. A row is: footswitch (0..4), report mode flag, last report value, reports above 0x3f,
@ reports at or below it, then events posted of type 1 (press), 2 (release), 3 (release before a hold), 5 (hold) and any other type.
@ tools/features/fs_probe.py chains fs_raw after the ring loop's flag read, fs_post before the event post and fs_paint after the Home paint.
.syntax unified
.thumb
.include "customos.inc"
.equ ROWS, 5
.equ LEFT, 4
.equ TOP, 64
.equ PITCH, 12
.equ SPACE, 16

.thumb_func
fs_raw:                             @ after the flag read 0x28dd83c4(r0 object, r1 code - 12); the ring loop keeps the report's code in r11, value in r10
    cmp r1, #ROWS
    bhs raw_out
    push {r4, lr}
    adr.w r4, fs_data
    add.w r4, r4, r1, lsl #4
    strb.w r10, [r4, #1]
    movs r2, #4
    cmp.w r10, #0x3f
    it hi
    movhi r2, #2
    ldrh r3, [r4, r2]
    adds r3, #1
    strh r3, [r4, r2]
    ldr r3, =0x28dd83c5             @ the flag again: the chain hands after-handlers the arguments, not the result
    blx r3
    strb r0, [r4]
    movs r0, #0
    movs r1, #1
    ldr r3, =0x28db8509             @ the redraw request (0, 1), so the rows follow without anything else repainting
    blx r3
    pop {r4, pc}
raw_out:
    bx lr

.thumb_func
fs_post:                            @ before the event post 0x28db8830(r0 event): {1 key, code, -, -, type}
    ldrb r1, [r0]
    cmp r1, #1
    bne post_out
    ldrb r1, [r0, #1]
    subs r1, #12
    cmp r1, #ROWS
    bhs post_out
    ldr r2, [r0, #4]
    cmp r2, #6
    it hs
    movhs r2, #6
    adr r3, slots
    ldrb r2, [r3, r2]
    adr.w r3, fs_data
    add.w r3, r3, r1, lsl #4
    ldrb r1, [r3, r2]
    adds r1, #1
    strb r1, [r3, r2]
    movs r0, #0
    movs r1, #1
    ldr r3, =0x28db8509             @ a hold or a click changes nothing the stock repaints for
    bx r3
post_out:
    bx lr

.thumb_func
fs_paint:                           @ after the Home paint (r0 the framebuffer)
    push {r3-r7, lr}
    sub sp, #64                     @ 0 the fill's stack arguments, 16 a row's glyphs
    mov r4, r0
    movs r3, #62
    str r3, [sp]
    movs r3, #0
    str r3, [sp, #4]
    str r3, [sp, #8]
    movs r1, #0
    movs r2, #4
    movw r3, #272
    ldr.w r12, =0x100017e9          @ the ROM fill (fb, x, y, w; h, colour, anchor 0: x, y the bottom left corner)
    blx r12
    movs r5, #0
row:
    add r6, sp, #16
    adr.w r7, fs_data
    add.w r7, r7, r5, lsl #4
    mov r0, r5
    movs r1, #1
    bl hex
    ldrb r0, [r7]
    movs r1, #2
    bl hex
    ldrb r0, [r7, #1]
    movs r1, #2
    bl hex
    ldrh r0, [r7, #2]
    movs r1, #4
    bl hex
    ldrh r0, [r7, #4]
    movs r1, #4
    bl hex
    ldrb r0, [r7, #6]
    movs r1, #2
    bl hex
    ldrb r0, [r7, #7]
    movs r1, #2
    bl hex
    ldrb r0, [r7, #8]
    movs r1, #2
    bl hex
    ldrb r0, [r7, #9]
    movs r1, #2
    bl hex
    ldrb r0, [r7, #10]
    movs r1, #2
    bl hex
    add r0, sp, #16
    sub.w r1, r6, r0
    movs r3, #PITCH
    mul r3, r5, r3
    rsb r3, r3, #TOP
    movs r2, #LEFT
    bl put
    adds r5, #1
    cmp r5, #ROWS
    bne row
    add sp, #64
    pop {r3-r7, pc}

hex:                                @ r0 a value, r1 how many hex digits, r6 where they go -> r6 past them and a space
    add r6, r1
    mov r2, r6
hex_digit:
    and r3, r0, #15
    strb r3, [r2, #-1]!
    lsrs r0, r0, #4
    subs r1, #1
    bne hex_digit
    movs r3, #SPACE
    strb r3, [r6], #1
    bx lr

put:                                @ r0 glyphs (0..15 hex, 16 space), r1 how many, r2 left edge, r3 top edge, r4 the framebuffer
    push {r5-r11, lr}
    sub sp, #16                     @ 0 fill height (the scale), 4 colour, 8 anchor, 12 top edge
    adr.w r12, style
    ldr r5, [r12]
    str r5, [sp]
    ldr r5, [r12, #4]
    str r5, [sp, #4]
    movs r5, #0
    str r5, [sp, #8]
    str r3, [sp, #12]
    mov r8, r0
    mov r7, r1
    mov r5, r2
    cmp r7, #0
    beq put_out
glyph:
    ldrb r0, [r8], #1
    adr.w r1, font
    ldrh.w r9, [r1, r0, lsl #1]
    ldr r6, [sp, #12]
    ldr r3, [sp]
    subs r6, r6, r3
    movs r10, #5
glyph_row:
    movs r11, #0
col:
    tst r9, #0x4000
    beq off
    ldr r3, [sp]
    mla r1, r11, r3, r5
    mov r2, r6
    mov r0, r4
    ldr.w r12, =0x100017e9
    blx r12
off:
    lsl.w r9, r9, #1
    adds r11, #1
    cmp r11, #3
    bne col
    ldr r3, [sp]
    subs r6, r6, r3
    subs r10, #1
    bne glyph_row
    ldr r3, [sp]
    add.w r5, r5, r3, lsl #2
    subs r7, #1
    bne glyph
put_out:
    add sp, #16
    pop {r5-r11, pc}

.ltorg
.balign 4
slots:                              @ an event type (6: any other) -> its count's byte in a footswitch's record
    .byte 10, 6, 7, 8, 10, 9, 10
.balign 4
style:
    .word 2, 0xffffff
font:                               @ 3x5 glyphs, bit 14 the top left pixel, rows of 3 bits: 0..9, A..F, space
    .hword 0b111101101101111, 0b010110010010111, 0b111001111100111, 0b111001111001111, 0b101101111001001
    .hword 0b111100111001111, 0b111100111101111, 0b111001001001001, 0b111101111101111, 0b111101111001111
    .hword 0b010101111101101, 0b110101110101110, 0b111100100100111, 0b110101101101110, 0b111100111100111
    .hword 0b111100111100100, 0
.balign 4
fs_data:                            @ per footswitch 16 bytes: 0 flag, 1 last value, 2 reports above 0x3f, 4 at or below, 6..10 event counts
    .space 16 * ROWS
