@ gr_meter.s - the DSP stream's receive callback with the gain-reduction meter on the Home divider.
@ Position independent; tools/m4asm.py turns it into the bytes patch_menu.py appends to the code segment.
@ Integer maths only: the thread has no FPU context of its own.
.syntax unified
.thumb
.global rx
.thumb_func
rx:
    push {r0-r7, lr}
    sub sp, #12
    mov r7, r1                      @ the frame
    ldr r0, [r7, #800]              @ the DSP's marker (600DF00D, halfwords swapped): until it is there, the UI is not up
    ldr r1, =0xf00d600d
    cmp r0, r1
    bne leave
    adr.w r4, data
    ldr r6, =0x28e1f845             @ the settings reader
    movs r0, #29                    @ GR Input
    mov r1, sp
    blx r6
    ldr r5, [sp, #4]
    movs r0, #104                   @ GR Output
    mov r1, sp
    blx r6
    ldr r1, [sp, #4]
    adr.w r2, maps
    and r5, r5, #3
    and r1, r1, #3
    ldrb r5, [r2, r5]
    adds r2, #4
    ldrb r1, [r2, r1]
    add.w r0, r7, #828              @ words 207..209: the peak of three buffers before the compressor
    ldr.w r0, [r0, r5, lsl #2]
    ror.w r0, r0, #16               @ the stream swaps halfwords
    add.w r2, r7, #840              @ words 210..212: after it
    ldr.w r2, [r2, r1, lsl #2]
    ror.w r2, r2, #16
    movs r3, #0                     @ the reduction, 0..65536
    ldr r1, =0x38d1b717             @ 1e-4: below it there is no signal to compare
    cmp r0, r1
    blo have_f
    ldr r1, =0x7fffff
    and r5, r0, r1
    orr r5, r5, #0x800000
    and r6, r2, r1
    orr r6, r6, #0x800000
    lsrs r0, r0, #23
    lsrs r2, r2, #23
    subs r2, r2, r0                 @ exponent of after / before
    lsrs r5, r5, #8
    lsls r6, r6, #8
    udiv r6, r6, r5                 @ mantissa ratio, 16 bit fraction
    cmp r2, #0
    blt neg
    cmp r2, #1
    bgt have_f
    lsls r6, r6, r2
    b calc
neg:
    rsbs r2, r2, #0
    cmp r2, #31
    bhs calc0
    lsrs r6, r6, r2
    b calc
calc0:
    movs r6, #0
calc:
    mov.w r3, #0x10000
    subs r3, r3, r6
    bge have_f
    movs r3, #0
have_f:
    ldr r5, [r4, #0]                @ the shown reduction: up at once, down slowly
    cmp r3, r5
    bhi attack
    subs r1, r5, r3
    lsrs r1, r1, #6
    subs r5, r5, r1
    b stored
attack:
    mov r5, r3
stored:
    str r5, [r4, #0]
    mov.w r1, #320
    muls r5, r1, r5
    lsrs r5, r5, #16
    bic r5, r5, #7                  @ the green width in pixels, in steps of 8
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
    movs r6, #0
seg:
    movs r1, #80
    mul r2, r6, r1
    subs r1, r5, r2
    ble blk
    cmp r1, #80
    ble green
    movs r1, #80
green:
    mov.w r7, #0xff00
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
leave:
    add sp, #12
    pop {r0-r7, lr}
    ldr r12, =0x10001095            @ on to the stock callback
    bx r12
.ltorg
.balign 4
maps:
    .byte 0, 1, 2, 0                @ GR Input -> buffer
    .byte 1, 0, 2, 1                @ GR Output -> buffer
data:
    .space 32
