@ gr_meter.s - a ten-light gain-reduction meter on the Home divider.
@ The divider's four stock segments and six more widgets of our own become ten 30 px lights at a 32 px pitch.
@ Meter Mode (setting 104): GR (A before over B after in dB, from 64-block window peaks, lights at 1 2 3 4 6 8 10 14 19 25 dB;
@ the measured gain already follows the comp's attack and release; the rise is slowed a little more by its Attack, and in silence
@ the lights decay at its Release),
@ or Level (96 dB log scale), Reduction (24 dB below 1.0), Wide (2^-20..2^20) of a word of the core's state (frame words 218..249).
@ Meter Source (setting 29): Map 0-9 .. Map 30-31 (each light is a state word, lit once it has changed since the page was chosen),
@ or Word 0..31 shown alone, its value also as the setting's text (k: XXXXXXXX). Words 0..3 are Threshold, Ratio, Attack, Release.
@ Entry table: +0 the DSP stream's receive callback, +4 the Home view's constructor, +8 its paint function, +12 Meter Source's text.
@ Position independent; tools/m4asm.py turns it into the bytes patch_menu.py appends to the code segment.
@ Integer maths only: the thread has no FPU context of its own.
.syntax unified
.thumb
.global rx
.thumb_func
rx:
    b.w hook
    b.w construct
    b.w paint
    b.w text

hook:
    push {r0-r7, lr}
    sub sp, #12
    mov r7, r1                      @ the frame
    adr.w r4, data
    ldr r0, [r7, #800]              @ the DSP's marker (600DF00D, halfwords swapped)
    ldr r1, =0xf00d600d
    subs r0, r0, r1
    str r0, [r4, #8]                @ 0: this frame carries the DSP's words
    ldr r1, [r4, #12]
    cbnz r0, nolatch
    movs r1, #1
    str r1, [r4, #12]
nolatch:
    cmp r1, #0
    beq leave                       @ until the DSP has been heard from, the UI may not be up
    ldr r0, [r4, #4]
    adds r0, #1
    str r0, [r4, #4]
    lsls r0, r0, #25
    bne noforce
    movs r0, #0                     @ now and then draw everything again: the layout code resets the stock segments
    movs r1, #10
    add.w r2, r4, #20
forget:
    str r0, [r2], #4
    subs r1, #1
    bne forget
noforce:
    ldr r6, =0x28e1f845             @ the settings reader
    movs r0, #29                    @ Meter Source
    mov r1, sp
    blx r6
    ldr r5, [sp, #4]
    movs r0, #104                   @ Meter Mode
    mov r1, sp
    blx r6
    ldr r1, [sp, #4]
    and r1, r1, #3
    ldr r0, [r4, #8]
    cmp r0, #0
    bne leave                       @ no measurement in this frame
    movs r6, #0
keep:                               @ the state words as last seen, for the setting's text
    add.w r0, r7, #872
    ldr.w r0, [r0, r6, lsl #2]
    add.w r2, r4, #320
    str.w r0, [r2, r6, lsl #2]
    adds r6, #1
    cmp r6, #32
    bne keep
    cmp r1, #0
    bne single
    ldr.w r0, [r7, #1000]           @ word 250: the DSP's window count; frames repeat a window's values
    ldr.w r1, [r4, #448]
    cmp r0, r1
    beq grshow
    str.w r0, [r4, #448]
    ldr r0, [r7, #864]              @ word 216: the window peak of A before, the compressor's input
    ldr r1, [r7, #868]              @ word 217: that of B after, its output
    bl grdb
    cmp r2, #0
    blt silent
    lsls r5, r2, #16
    ldr r1, [r4, #0]
    cmp r5, r1
    bls decayed_to                  @ falling: as measured
    ldr.w r0, [r7, #1008]           @ word 252: the comp's Attack coefficient over half a window
    bl q16
    subs r1, r5, r1                 @ rising: the target less what is left of the gap
    umull r2, r3, r1, r0
    lsrs r2, r2, #16
    orr.w r2, r2, r3, lsl #16
    subs r5, r5, r2
decayed_to:
    str r5, [r4, #0]
    b grshow
silent:                             @ nothing to measure: the comp's gain recovers at its Release
    ldr.w r0, [r7, #1004]           @ word 251: its coefficient over one window
    bl q16
    ldr r1, [r4, #0]
    umull r2, r3, r1, r0
    lsrs r2, r2, #16
    orr.w r2, r2, r3, lsl #16
    str r2, [r4, #0]
grshow:
    ldr r2, [r4, #0]
    lsrs r2, r2, #16
    adr.w r3, lights
    movs r5, #0                     @ the lights lit
light:
    ldrh.w r0, [r3, r5, lsl #1]
    cmp r2, r0
    blo count
    adds r5, #1
    cmp r5, #10
    bne light
    b count
single:
    cmp r5, #4
    blo map
    subs r5, #4
    cmp r5, #32
    bhs leave
    add.w r0, r7, #872              @ words 218..249: the core's state
    ldr.w r0, [r0, r5, lsl #2]
    bl measure
    mov r3, r4
    bl smooth
    adds r2, #16
    lsrs r5, r2, #5                 @ 32 px a light
count:
    movs r0, #0                     @ not on a map page: choosing one again re-arms it
    str.w r0, [r4, #316]
    movs r0, #1                     @ the first r5 lights
    lsls r0, r0, r5
    subs r5, r0, #1
    b draw

map:                                @ r5 the page: light k shows word 10 * page + k, lit once it has changed (blinks are too quick to see)
    ldr.w r0, [r4, #316]
    adds r1, r5, #1
    cmp r0, r1
    beq armed
    str.w r1, [r4, #316]            @ a page newly chosen: the words now are the baseline, all lights off
    movs r6, #0
rearm:
    add.w r0, r7, #872
    ldr.w r0, [r0, r6, lsl #2]
    add.w r2, r4, #60
    str.w r0, [r2, r6, lsl #2]
    add.w r2, r4, #188
    movs r0, #0
    str.w r0, [r2, r6, lsl #2]
    adds r6, #1
    cmp r6, #32
    bne rearm
armed:
    movs r6, #0
act:
    add.w r0, r7, #872
    ldr.w r0, [r0, r6, lsl #2]
    add.w r2, r4, #60
    ldr.w r3, [r2, r6, lsl #2]
    str.w r0, [r2, r6, lsl #2]
    cmp r0, r3
    beq same
    add.w r2, r4, #188
    movs r3, #1
    str.w r3, [r2, r6, lsl #2]
same:
    adds r6, #1
    cmp r6, #32
    bne act
    movs r0, #10
    mul r5, r5, r0
    movs r1, #0
    movs r6, #0
mbit:
    add.w r0, r5, r6
    cmp r0, #32
    bhs mnext
    add.w r2, r4, #188
    ldr.w r0, [r2, r0, lsl #2]
    cbz r0, mnext
    movs r0, #1
    lsls r0, r0, r6
    orrs r1, r0
mnext:
    adds r6, #1
    cmp r6, #10
    bne mbit
    mov r5, r1

draw:                               @ r5 the lights lit, a bit each: each its own colour, the rest black
    movs r6, #0
piece:
    movs r1, #0
    lsr.w r0, r5, r6
    tst r0, #1
    beq unlit
    adr.w r3, colours
    ldr.w r1, [r3, r6, lsl #2]
unlit:
    orr r0, r1, #0x1000000          @ never 0, which means not drawn yet
    add.w r2, r4, #20
    ldr.w r3, [r2, r6, lsl #2]
    cmp r3, r0
    beq pnext
    str.w r0, [r2, r6, lsl #2]
    movs r0, #1
    str r0, [r4, #16]               @ the screen needs repainting
    mov r0, r6
    bl widget
    ldr r3, =0x28e24b99             @ setColor
    blx r3
pnext:
    adds r6, #1
    cmp r6, #10
    bne piece
    ldr r0, [r4, #16]               @ the setters only mark the canvas: ask the UI to repaint, at most every 16 frames
    cbz r0, leave
    ldr r0, [r4, #4]
    lsls r0, r0, #28
    bne leave
    movs r0, #0
    str r0, [r4, #16]
    movs r1, #1
    ldr r3, =0x28db8509             @ the redraw request the layout code ends with: (0, 1)
    blx r3
leave:
    add sp, #12
    pop {r0-r7, lr}
    ldr r12, =0x10001095            @ on to the stock callback
    bx r12

widget:                             @ r0 a light, 0..9 -> r0 its widget; keeps r1
    cmp r0, #4
    bhs ours
    movs r2, #0x1c
    mul r0, r0, r2
    ldr r2, =0x2812a594             @ the Home view's four divider segments
    add r0, r2
    bx lr
ours:
    subs r0, #4
    movs r2, #0x1c
    mul r0, r0, r2
    adr.w r2, widgets
    add r0, r2
    bx lr

construct:                          @ r0 the Home view: the stock constructor, then six more lights and all ten placed
    push {r4-r7, lr}
    mov r4, r0
    ldr r3, =0x28dc91d1
    blx r3
    adr.w r5, widgets
    adr.w r6, nodes
    movs r7, #4
make:
    mov r0, r5
    mov r1, r6
    ldr r3, =0x28e24989             @ init(widget, node)
    blx r3
    mov r0, r5
    movs r1, #6
    ldr r3, =0x28e24a19             @ the layer the stock segments use
    blx r3
    mov r0, r5
    mov.w r1, #0xff00
    ldr r3, =0x28e24b99             @ setColor
    blx r3
    mov r0, r5                      @ placed before it is sized: its first erase then covers only itself
    lsls r1, r7, #5                 @ x: 32 px a light
    movs r2, #0x77                  @ y: the stock divider's
    ldr r3, =0x28e24af1             @ setPos
    blx r3
    mov r0, r5
    movs r1, #30
    movs r2, #2
    ldr r3, =0x28e24b29             @ setSize
    blx r3
    adds r5, #0x1c
    adds r6, #0x28
    adds r7, #1
    cmp r7, #10
    bne make
    movs r7, #0
place:                              @ the stock four, to the same pitch
    mov r0, r7
    bl widget
    lsls r1, r7, #5
    movs r2, #0x77
    ldr r3, =0x28e24af1             @ setPos
    blx r3
    adds r7, #1
    cmp r7, #4
    bne place
    pop {r4-r7, pc}

paint:                              @ r0 the framebuffer, r1 the Home view: like the stock paint, every erase before any draw
    push {r3-r7, lr}
    mov r4, r0
    mov r5, r1
    add.w r0, r5, #0x538
    ldrb r7, [r0, #0x15]            @ ours are shown while the stock divider is
    adr.w r6, widgets
    ldrb r0, [r6, #0x15]
    cmp r0, r7
    beq synced
hide:
    mov r0, r6
    mov r1, r7
    ldr r3, =0x28e24b01             @ setVisible
    blx r3
    adds r6, #0x1c
    adr.w r0, nodes                 @ the end of our widgets
    cmp r6, r0
    bne hide
synced:
    ldr r3, =0x28e24b41             @ erase(context, context, widget): the old place
    bl each
    mov r0, r4
    mov r1, r5
    ldr r3, =0x28dc8d39             @ the stock paint
    blx r3
    ldr r3, =0x28e24b59             @ draw(context, context, widget): in its colour
    bl each
    movs r0, #0
    pop {r3-r7, pc}

each:                               @ r3 a function (context, context, widget) for our six widgets, r4 the context
    push {r5-r7, lr}
    mov r7, r3
    ldr r3, =0x28e24971             @ the widget lock, as the stock paint takes it
    blx r3
    adr.w r6, widgets
    movs r5, #6
each6:
    mov r0, r4
    mov r1, r4
    mov r2, r6
    blx r7
    adds r6, #0x1c
    subs r5, #1
    bne each6
    ldr r3, =0x28e24ae9
    blx r3
    pop {r5-r7, pc}

text:                               @ r0 the value string, r1 Meter Source (4..35): "k: XXXXXXXX", state word k as last seen
    push {r4, r5, lr}
    adr.w r4, data
    mov r5, r0
    subs r1, #4
    mov r3, r1
    movs r2, #0
tens:
    cmp r1, #10
    blo units
    subs r1, #10
    adds r2, #1
    b tens
units:
    cbz r2, notens
    adds r2, #48
    strb r2, [r5], #1
notens:
    adds r1, #48
    strb r1, [r5], #1
    movs r0, #':'
    strb r0, [r5], #1
    movs r0, #' '
    strb r0, [r5], #1
    add.w r0, r4, #320
    ldr.w r1, [r0, r3, lsl #2]
    ror.w r1, r1, #16               @ the stream swaps halfwords
    movs r3, #8
hexdigit:
    subs r3, #1
    lsl.w r2, r3, #2
    lsr.w r0, r1, r2
    and r0, r0, #15
    adds r0, #48
    cmp r0, #57
    it hi
    addhi r0, #7
    strb r0, [r5], #1
    cmp r3, #0
    bne hexdigit
    movs r0, #0
    strb r0, [r5]
    pop {r4, r5, pc}

q16:                                @ r0 a frame word, a float in 0..2 -> r0 in Q16; keeps r1, r5
    ror.w r0, r0, #16               @ the stream swaps halfwords
    lsrs r2, r0, #23
    rsb.w r2, r2, #134
    cmp r2, #32
    bhs q16zero
    ubfx r0, r0, #0, #23
    orr r0, r0, #0x800000
    lsr.w r0, r0, r2
    bx lr
q16zero:
    movs r0, #0
    bx lr

grdb:                               @ r0, r1 frame words: input and output peaks -> r2 the reduction in 1/256 octaves, 0..1500, or -1 in silence
    push {r4, r5, lr}
    mov r4, r1
    bl lg
    mov r5, r0
    mov r0, r4
    bl lg
    mov.w r2, #-1
    movw r1, #29440                 @ below -72 dB there is nothing to compare
    cmp r5, r1
    blo grout
    subs r2, r5, r0
    it lt
    movlt r2, #0
    movw r1, #1500
    cmp r2, r1
    it gt
    movgt r2, r1
grout:
    pop {r4, r5, pc}

lg:                                 @ r0 a frame word -> r0 log2 of its magnitude in 1/256 octaves, 1.0 = 32512
    ror.w r0, r0, #16               @ the stream swaps halfwords
    bic r0, r0, #0x80000000
    ubfx r1, r0, #15, #8
    lsrs r0, r0, #15
    rsb.w r3, r1, #256              @ log2(1 + m) ~ m + 0.346 m (1 - m): within 0.14 dB
    mul r3, r3, r1
    movs r2, #89
    mul r3, r3, r2
    add.w r0, r0, r3, lsr #16
    bx lr

measure:                            @ r0 a frame word, r1 the mode -> r2 the width, 0..320
    ror.w r0, r0, #16
    bic r0, r0, #0x80000000
    lsrs r2, r0, #19                @ log2 in 1/16 octaves, 1.0 = 2032
    cmp r1, #1
    bhi notlevel
    subw r2, r2, #1776              @ 16 octaves below 1.0 .. 1.0
    add.w r2, r2, r2, lsl #2
    asrs r2, r2, #2
    b clamp
notlevel:
    cmp r1, #2
    bne linear
    rsb.w r2, r2, #2032             @ 4 octaves below 1.0 = full width
    add.w r2, r2, r2, lsl #2
    b clamp
linear:                             @ Wide: 2^-20 .. 2^20
    subw r2, r2, #1712
    asrs r2, r2, #1
clamp:
    cmp r2, #0
    it lt
    movlt r2, #0
    cmp.w r2, #320
    it gt
    movgt.w r2, #320
    bx lr

smooth:                             @ r2 a value, r3 its state -> r2 the shown value: up at once, down slowly
    lsls r2, r2, #16
    ldr r1, [r3]
    cmp r2, r1
    bhs up
    subs r0, r1, r2
    lsrs r0, r0, #6
    subs r2, r1, r0
up:
    str r2, [r3]
    lsrs r2, r2, #16
    bx lr

.ltorg
.balign 4
lights:                             @ a compressor pedal's GR lights, 1 2 3 4 6 8 10 14 19 25 dB, in 1/256 octaves
    .hword 43, 85, 128, 170, 255, 340, 425, 595, 808, 1063
colours:                            @ lights 1..10
    .word 0x00ff00, 0x66ff00, 0xb3ff00, 0xffff00, 0xffd000, 0xffa500, 0xff7f00, 0xff5500, 0xff2a00, 0xff0000
data:                               @ 0 shown value, 4 frames, 8 marker, 12 latch, 16 repaint, 20 colours drawn (10),
    .space 452                      @ 60 the state words last seen (32), 188 changed since armed (32), 316 map page armed + 1,
                                    @ 320 the state words for the text (32), 448 the last window seen
widgets:                            @ lights 5..10
    .space 6 * 0x1c
nodes:                              @ their backing nodes
    .space 6 * 0x28
