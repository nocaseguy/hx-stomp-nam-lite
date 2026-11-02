@ gr_meter.s - the DSP stream's receive callback with a diagnostic meter on the Home divider.
@ Meter Source (setting 29): buffer A, B or C of the Deluxe Comp's core, or Test (green/black/green/black; red when the frame lacks the DSP's marker).
@ Meter Mode (setting 104): Level Pre / Level Post (the peak before/after the stock code, 96 dB log scale), Reduction (24 dB below 1.0), Linear (0..1).
@ With Source = Test the Source setting's text shows the hook's counters (text, below): C frames, M frames with the marker, D draws; W word 200 while M is 0.
@ Position independent; tools/m4asm.py turns it into the bytes patch_menu.py appends to the code segment.
@ Integer maths only: the thread has no FPU context of its own.
.syntax unified
.thumb
.global rx
.thumb_func
rx:                                 @ entry table: the receive callback at +0, the text function at +4
    b.w hook
    b.w text
hook:
    push {r0-r7, lr}
    sub sp, #12
    mov r7, r1                      @ the frame
    adr.w r4, data
    ldr r0, [r4, #32]
    adds r0, #1
    str r0, [r4, #32]
    ldr r0, [r7, #800]              @ the DSP's marker (600DF00D, halfwords swapped)
    str r0, [r4, #44]
    ldr r1, =0xf00d600d
    subs r0, r0, r1
    str r0, [r4, #8]                @ 0: this frame carries the DSP's words
    ldr r1, [r4, #12]
    cbnz r0, nolatch
    movs r1, #1
    str r1, [r4, #12]
    ldr r0, [r4, #36]
    adds r0, #1
    str r0, [r4, #36]
nolatch:
    cmp r1, #0
    beq leave                       @ until the DSP has been heard from, the UI may not be up
    ldr r0, [r4, #4]
    adds r0, #1
    str r0, [r4, #4]
    lsls r0, r0, #25
    bne noforce
    movs r0, #0                     @ now and then draw everything again: the layout code resets the segments
    str r0, [r4, #16]
    str r0, [r4, #20]
    str r0, [r4, #24]
    str r0, [r4, #28]
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
    cmp r5, #3
    beq test
    cmp r0, #0
    bne leave                       @ no measurement in this frame
    add.w r0, r7, #828              @ words 207..209: the peaks before the stock code, 210..212 after it
    cmp r1, #0
    it ne
    addne r0, #12
    ldr.w r0, [r0, r5, lsl #2]
    ror.w r0, r0, #16               @ the stream swaps halfwords
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
    lsls r2, r2, #16                @ the shown width: up at once, down slowly
    ldr r3, [r4, #0]
    cmp r2, r3
    bhs attack
    subs r0, r3, r2
    lsrs r0, r0, #6
    subs r2, r3, r0
attack:
    str r2, [r4, #0]
    lsrs r5, r2, #16
    bic r5, r5, #7                  @ in steps of 8 px
    mov.w r0, #0xff00
    str r0, [sp, #4]
    b draw
test:
    mov.w r1, #0xff00
    cmp r0, #0
    it ne
    movne.w r1, #0xff0000
    str r1, [sp, #4]
    mov.w r5, #-1
draw:
    movs r6, #0
seg:
    ldr r7, [sp, #4]
    movs r1, #80
    cmn r5, #1
    bne meter
    tst r6, #1
    bne blk
    b have
meter:
    mul r2, r6, r1
    subs r1, r5, r2
    ble blk
    cmp r1, #80
    ble have
    movs r1, #80
    b have
blk:
    movs r1, #80
    movs r7, #0
have:
    add.w r0, r1, r7, lsl #8        @ what this segment shows: width and colour
    adds r2, r4, #16
    ldr.w r3, [r2, r6, lsl #2]
    cmp r3, r0
    beq next
    str.w r0, [r2, r6, lsl #2]
    ldr r0, [r4, #40]
    adds r0, #1
    str r0, [r4, #40]
    movs r0, #1
    str r0, [r4, #48]               @ the screen needs repainting
    movs r2, #0x1c
    mul r2, r6, r2
    ldr r0, =0x2812a594             @ the first divider segment of the Home view
    add r0, r2
    str r0, [sp, #0]
    str r1, [sp, #8]
    mov r1, r7
    ldr r3, =0x28e24b99             @ setColor
    blx r3
    ldr r0, [sp, #0]
    ldr r1, [sp, #8]
    movs r2, #2
    ldr r3, =0x28e24b29             @ setSize
    blx r3
next:
    adds r6, #1
    cmp r6, #4
    bne seg
    ldr r0, [r4, #48]               @ the setters only mark the canvas: ask the UI to repaint, at most every 16 frames
    cbz r0, leave
    ldr r0, [r4, #4]
    lsls r0, r0, #28
    bne leave
    movs r0, #0
    str r0, [r4, #48]
    movs r1, #1
    ldr r3, =0x28db8509             @ the redraw request the layout code ends with: (0, 1)
    blx r3
leave:
    add sp, #12
    pop {r0-r7, lr}
    ldr r12, =0x10001095            @ on to the stock callback
    bx r12

text:                               @ r0 = the value string to fill; runs in the UI thread
    push {r4, r5, lr}
    adr.w r4, data
    mov r5, r0
    movs r0, #'C'
    ldr r1, [r4, #32]
    movs r3, #4
    bl field
    ldr r1, [r4, #36]
    cbz r1, nomark
    movs r0, #'M'
    movs r3, #4
    bl field
    movs r0, #'D'
    ldr r1, [r4, #40]
    movs r3, #4
    bl field
    b tend
nomark:
    movs r0, #'W'
    ldr r1, [r4, #44]
    movs r3, #8
    bl field
tend:
    movs r0, #0
    strb r0, [r5, #-1]              @ over the last space
    pop {r4, r5, pc}

field:                              @ r0 letter, r1 value, r3 hex digits, r5 out: "L" + digits + " "
    strb r0, [r5], #1
digit:
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
    bne digit
    movs r0, #' '
    strb r0, [r5], #1
    bx lr

.ltorg
.balign 4
data:
    .space 52
