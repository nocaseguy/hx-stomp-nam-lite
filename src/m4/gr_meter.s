@ gr_meter.s - a ten-light gain-reduction meter on the Home divider.
@ The divider's four stock segments and six more widgets of our own become ten 30 px lights at a 32 px pitch.
@ Meter Mode (setting 104): GR (A before over B after in dB, from 128-block window peaks, lights at 1 2 3 4 6 8 10 14 19 25 dB),
@ or Level (96 dB log scale), Reduction (24 dB below 1.0), Linear (0..1) of buffer A, B or C (Meter Source, setting 29).
@ Entry table: +0 the DSP stream's receive callback, +4 the Home view's constructor, +8 its paint function.
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
    and r5, r5, #3
    and r1, r1, #3
    ldr r0, [r4, #8]
    cmp r0, #0
    bne leave                       @ no measurement in this frame
    cmp r1, #0
    bne single
    ldr r0, [r7, #864]              @ word 216: the window peak of A before, the compressor's input
    ldr r1, [r7, #868]              @ word 217: that of B after, its output
    bl grdb
    mov r3, r4
    bl smooth
    adr.w r3, lights
    movs r5, #0                     @ the lights lit
light:
    ldrh.w r0, [r3, r5, lsl #1]
    cmp r2, r0
    blo draw
    adds r5, #1
    cmp r5, #10
    bne light
    b draw
single:
    cmp r5, #3
    it eq
    moveq r5, #0
    add.w r0, r7, #840              @ words 210..212: the peaks after the stock code
    ldr.w r0, [r0, r5, lsl #2]
    bl measure
    mov r3, r4
    bl smooth
    adds r2, #16
    lsrs r5, r2, #5                 @ 32 px a light

draw:                               @ r5 lights lit: each its own colour, the rest black
    movs r6, #0
piece:
    movs r1, #0
    cmp r6, r5
    bhs unlit
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

grdb:                               @ r0, r1 frame words: input and output peaks -> r2 the reduction in 1/256 octaves, 0..1500
    push {r4, r5, lr}
    mov r4, r1
    bl lg
    mov r5, r0
    mov r0, r4
    bl lg
    movs r2, #0
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
linear:
    lsrs r3, r0, #23
    rsb.w r3, r3, #127
    cmp r3, #0
    ble full
    adds r3, #15
    cmp r3, #32
    bhs zero
    ubfx r2, r0, #0, #23
    orr r2, r2, #0x800000
    lsrs r2, r2, #8
    mov.w r12, #320
    mul r2, r2, r12
    lsr.w r2, r2, r3
    b clamp
full:
    mov.w r2, #320
    b clamp
zero:
    movs r2, #0
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
data:                               @ 0 shown value, 4 frames, 8 marker, 12 latch, 16 repaint, 20 colours drawn (10)
    .space 60
widgets:                            @ lights 5..10
    .space 6 * 0x1c
nodes:                              @ their backing nodes
    .space 6 * 0x28
