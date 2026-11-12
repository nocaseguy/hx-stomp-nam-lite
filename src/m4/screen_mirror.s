@ screen_mirror.s - HX Edit's editor service gets one more command, CMD: it replies with the frame the LCD shows, coded as changes
@ to the frame it sent before, so a computer can mirror the screen (tools/hx_mirror.py). The reply is the editor's own: {0x66: seq,
@ 0x67: 0, 0x68: bin32}, the bin32 being halfwords over the framebuffer's pixels in order (column-major, bottom-up, 5-6-5 blue
@ high): c < SKIP, then c pixels; SKIP + c: c pixels as before; RUN + c, then one pixel c times; then 0, the count n of UI events
@ posted since the last reply (at most RING), n records {u32 µs, the 8-byte event}, the footswitch rings' LEDs as three u32
@ {colour as the driver keeps it, its mode on top} and three u32: the µs the frame was taken at, the µs coding it took and sending
@ it; all as halfwords, low first. sm_event logs each event as it is posted, for a video that
@ shows the controls being used (tools/hx_mirror.py). A request whose seq does not follow the last one's (a new session, or
@ another command in between) gets every pixel, with no skips. USB carries about 0.5 MB/s, so bytes are what the frame rate
@ costs; and code runs from uncached SDRAM, so each instruction counts. tools/features/screen_mirror.py chains sm_register after
@ the editor's command registration at boot.
.syntax unified
.thumb
.include "usb.inc"                  @ CMD: this feature's line in tools/usb_commands.py
.equ SERVICE, 6                     @ the editor
.equ FB0, 0x28d1ce98                @ the first of the three framebuffers
.equ FB_BYTES, 0x25800              @ 320 x 240 x 2
.equ LCD_UPBASE, 0x40008010         @ the LCD controller's frame address: the buffer on screen
.equ REGISTER, 0x28e165f1           @ (command, {handler, check, 0}): the editor's command table
.equ NO_PARAMS, 0x28e19205          @ the check of the commands that take no parameters
.equ WRITER, 0x28e157c9             @ (service) -> the service's reply writer {context, write(context, bytes, n)}
.equ PREFIX_LEN, 0x28e157ed         @ (service) -> the word counting the bytes it holds
.equ PREFIX, 0x28e15811             @ (service) -> those bytes
.equ PREFIX_RESET, 0x28e15835       @ (service): empties it
.equ REPLY_HEAD, 0x28e15879         @ (writer, seq, status): the reply map's head, up to the result's key
.equ LOCK, 0x28e24c01               @ (stream - 8): the stream's lock, held around a reply's writes
.equ UNLOCK, 0x28e24bb1
.equ CLOCK, 0x28da6459              @ () -> µs
.equ SLEEP, 0x28e24c59              @ (µs): the task sleeps, so others run
.equ YIELD_BYTES, FB_BYTES / 8      @ the coding sleeps each time it passes another eighth of the frame: knob turns waited for it
.equ YIELD_US, 1000
.equ BIN32, 0xc6
.equ RUN, 0x8000
.equ SKIP, 0x4000
.equ MAX_RUN_BYTES, 2 * 0x7fff      @ a count's most, in bytes of frame
.equ MAX_SKIP, 0x3fff
.equ MAX_LITERAL_BYTES, 2 * 0x3fff
.equ TRAILER, 12                    @ bytes: the frame's µs, then the coding's and the sending's
.equ RING, 64                       @ events kept for the next reply: a power of two
.equ LED_COLOURS, 0x281f35e0        @ the LED driver's colour of each footswitch ring: 3 bytes each, as the LED send takes it
.equ LED_MODES, 0x281f35f8          @ and its mode: 0 off, 1 on, 2 blinking
.equ LEDS, 3
.equ EVENT, 12                      @ a record's bytes: µs, then the event
.equ CHUNK, 4096                    @ bytes sent at a time

sm_register:                        @ after the editor registers its commands at boot: CMD too
    push {r4, lr}
    sub sp, #16
    adr.w r0, sm_cmd
    orr r0, r0, #1
    ldr r1, =NO_PARAMS
    movs r2, #0
    str r0, [sp, #4]
    str r1, [sp, #8]
    str r2, [sp, #12]
    movs r0, #CMD
    add r1, sp, #4
    ldr r3, =REGISTER
    blx r3
    add sp, #16
    pop {r4, pc}

sm_cmd:                             @ r0 the editor's stream, r1 the request -> r0 the stream's result
    push {r4-r11, lr}
    sub sp, #20                     @ [sp] the headers, [sp, #8] a start time, [sp, #12] the coding's time, [sp, #16] the frame's
    mov r10, r0
    ldrh r9, [r1, #0xc]             @ the request's seq
    adr.w r3, sm_seq
    ldr r2, [r3]
    str r9, [r3]
    adds r2, #1
    uxth r2, r2
    cmp r9, r2
    ite eq
    moveq r4, #0
    movne r4, #1                    @ every pixel: the host may not hold the frame before
    cmp r9, #1
    it eq
    moveq r4, #1
    ldr r3, =LCD_UPBASE
    ldr r11, [r3]
    ldr r0, =FB0
    subs r1, r11, r0
    ldr r2, =FB_BYTES * 3
    cmp r1, r2
    it hs
    movhs r11, r0                   @ not a framebuffer (the LCD not set up yet): the first one
    ldr r3, =CLOCK
    blx r3
    str r0, [sp, #8]
    str r0, [sp, #16]
    mov r0, r11
    adr.w r1, sm_prev
    add.w r1, r1, #FB_BYTES         @ sm_out, beyond adr's reach
    mov r2, r4
    bl sm_encode
    mov r8, r0                      @ the coded frame's bytes
    adr.w r0, sm_prev
    add.w r0, r0, #FB_BYTES
    add r0, r8
    bl sm_events_out
    add r8, r0
    ldr r3, =CLOCK
    blx r3
    ldr r1, [sp, #8]
    subs r0, r0, r1
    str r0, [sp, #12]
    movs r0, #SERVICE
    ldr r3, =WRITER
    blx r3
    mov r5, r0
    movs r0, #SERVICE
    ldr r3, =PREFIX_LEN
    blx r3
    mov r6, r0
    movs r0, #SERVICE
    ldr r3, =PREFIX
    blx r3
    mov r7, r0
    movs r0, #SERVICE
    ldr r3, =PREFIX_RESET
    blx r3
    mov r0, r5
    mov r1, r9
    movs r2, #0
    ldr r3, =REPLY_HEAD
    blx r3
    add r4, r8, #TRAILER            @ the result's bytes
    movs r0, #BIN32
    strb r0, [sp]
    lsrs r0, r4, #24
    strb r0, [sp, #1]
    lsrs r0, r4, #16
    strb r0, [sp, #2]
    lsrs r0, r4, #8
    strb r0, [sp, #3]
    strb r4, [sp, #4]
    ldr r0, [r5]
    ldr r3, [r5, #4]
    mov r1, sp
    movs r2, #5
    blx r3
    sub.w r0, r10, #8
    ldr r3, =LOCK
    blx r3
    movs r0, #0
    strh r0, [sp]
    movs r0, #SERVICE
    strh r0, [sp, #2]
    ldr r0, [r6]
    add r0, r4
    str r0, [sp, #4]                @ the message: the prefix and the result
    mov r1, sp
    movs r2, #8
    bl sm_write
    mov r1, r7
    ldr r2, [r6]
    bl sm_write
    ldr r3, =CLOCK
    blx r3
    str r0, [sp, #8]
    adr.w r5, sm_prev
    add.w r5, r5, #FB_BYTES
    mov r6, r8
sm_send:
    cbz r6, sm_sent
    mov r1, r5
    mov r2, r6
    cmp r2, #CHUNK
    it hi
    movhi r2, #CHUNK
    add r5, r2
    sub r6, r2
    bl sm_write
    b sm_send
sm_sent:
    ldr r3, =CLOCK
    blx r3
    ldr r1, [sp, #8]
    subs r0, r0, r1
    adr.w r1, sm_trailer
    str r0, [r1, #8]
    ldr r0, [sp, #12]
    str r0, [r1, #4]
    ldr r0, [sp, #16]
    str r0, [r1]
    movs r2, #TRAILER
    bl sm_write
    mov r0, r10
    movs r1, #0
    ldr r3, [r10]
    ldr r3, [r3, #0xc]
    blx r3                          @ the message is complete
    mov r4, r0
    sub.w r0, r10, #8
    ldr r3, =UNLOCK
    blx r3
    mov r0, r4
    add sp, #20
    pop {r4-r11, pc}

sm_event:                           @ before each UI event's post: r0 the 8-byte event, logged with the µs clock
    push {r4, lr}
    mov r4, r0
    ldr r3, =CLOCK
    blx r3
    adr.w r1, sm_events
    ldr r2, [r1]                    @ the events ever logged
    and r3, r2, #RING - 1
    add r3, r3, r3, lsl #1
    add r3, r1, r3, lsl #2
    str r0, [r3, #4]
    ldr r0, [r4]
    str r0, [r3, #8]
    ldr r0, [r4, #4]
    str r0, [r3, #12]
    adds r2, #1
    str r2, [r1]                    @ counted once written: the reply reads up to the count
    pop {r4, pc}

sm_events_out:                      @ r0 where: 0, n, the events logged since the last reply and the LEDs, as halfwords -> r0 the bytes
    push {r4-r6, lr}
    adr.w r1, sm_events
    ldr r2, [r1]
    adr.w r3, sm_events_sent
    ldr r4, [r3]
    str r2, [r3]
    subs r5, r2, r4
    cmp r5, #RING
    itt hi
    movhi r5, #RING
    subhi r4, r2, #RING             @ more than the ring holds: the newest
    mov r6, r0
    movs r3, #0
    strh r3, [r6], #2
    strh r5, [r6], #2
sm_events_next:
    cbz r5, sm_events_done
    and r3, r4, #RING - 1
    add r3, r3, r3, lsl #1
    add r3, r1, r3, lsl #2
    ldrh r2, [r3, #4]
    strh r2, [r6], #2
    ldrh r2, [r3, #6]
    strh r2, [r6], #2
    ldrh r2, [r3, #8]
    strh r2, [r6], #2
    ldrh r2, [r3, #10]
    strh r2, [r6], #2
    ldrh r2, [r3, #12]
    strh r2, [r6], #2
    ldrh r2, [r3, #14]
    strh r2, [r6], #2
    adds r4, #1
    subs r5, #1
    b sm_events_next
sm_events_done:
    mov r5, r0
    ldr r1, =LED_COLOURS
    ldr r12, =LED_MODES
    movs r3, #0
sm_leds:
    add r2, r3, r3, lsl #1
    add r2, r1
    ldrb r0, [r2]
    ldrb r4, [r2, #1]
    orr r0, r0, r4, lsl #8
    ldrb r4, [r2, #2]
    orr r0, r0, r4, lsl #16
    ldrb r4, [r12, r3]
    orr r0, r0, r4, lsl #24
    strh r0, [r6], #2
    lsrs r0, r0, #16
    strh r0, [r6], #2
    adds r3, #1
    cmp r3, #LEDS
    blo sm_leds
    sub r0, r6, r5
    pop {r4-r6, pc}

sm_write:                           @ r1 bytes, r2 how many: to the stream, r10
    mov r0, r10
    ldr r3, [r10]
    ldr r3, [r3, #4]
    bx r3

sm_encode:                          @ r0 a frame, r1 the output, r2 1 for every pixel -> r0 the bytes coded; sm_prev becomes the frame
    push {r4-r11, lr}
    sub sp, #12                     @ [sp] the output's start, [sp, #4] where to sleep next, [sp, #8] the frame's end
    str r1, [sp]
    mov r4, r0                      @ the next pixel
    ldr r5, =FB_BYTES
    add r5, r0                      @ the frame's end
    str r5, [sp, #8]
    add r3, r0, #YIELD_BYTES
    str r3, [sp, #4]
    mov r6, r1                      @ the next output halfword
    adr.w r8, sm_prev
    subs r8, r8, r0                 @ from a pixel to its place in sm_prev
    mov r11, r2
sm_next:
    cmp r4, r5
    bhs sm_coded
    ldr r0, [sp, #4]
    cmp r4, r0
    blo sm_awake
sm_later:
    add r0, r0, #YIELD_BYTES
    cmp r4, r0
    bhs sm_later
    str r0, [sp, #4]
    ldr r0, =YIELD_US
    ldr r3, =SLEEP
    blx r3
sm_awake:
    cmp r11, #0
    bne sm_changed
    ldr r5, [sp, #4]                @ the unchanged scan stops where the coding sleeps next, so a still frame sleeps too
    ldr r0, [sp, #8]
    cmp r5, r0
    it hi
    movhi r5, r0
    mov r7, r4                      @ as far as the pixels are as before: eight words a step, then two, then one pixel
    tst r7, #2
    beq sm_same_eights
    ldrh r0, [r7]
    ldrh r1, [r7, r8]
    cmp r0, r1
    bne sm_same_end
    adds r7, #2
sm_same_eights:                     @ r9..r11 and lr hold sm_prev's words here; r11 (every pixel) is 0 on this path
    add r2, r7, #32
    cmp r2, r5
    bhi sm_same_eights_end
    add r12, r7, r8
    ldm r7, {r0, r1, r2, r3}
    ldm r12, {r9, r10, r11, lr}
    cmp r0, r9
    bne sm_same_eights_end
    cmp r1, r10
    bne sm_same_eights_end
    cmp r2, r11
    bne sm_same_eights_end
    cmp r3, lr
    bne sm_same_eights_end
    add r12, #16
    ldrd r0, r1, [r7, #16]
    ldrd r2, r3, [r7, #24]
    ldm r12, {r9, r10, r11, lr}
    cmp r0, r9
    bne sm_same_half
    cmp r1, r10
    bne sm_same_half
    cmp r2, r11
    bne sm_same_half
    cmp r3, lr
    bne sm_same_half
    adds r7, #32
    b sm_same_eights
sm_same_half:
    adds r7, #16
sm_same_eights_end:
    mov.w r11, #0
sm_same_words:
    add r2, r7, #8
    cmp r2, r5
    bhi sm_same_tail
    add r12, r7, r8
    ldrd r0, r1, [r7]
    ldrd r2, r3, [r12]
    cmp r0, r2
    bne sm_same_tail
    cmp r1, r3
    bne sm_same_tail
    adds r7, #8
    b sm_same_words
sm_same_tail:
    cmp r7, r5
    bhs sm_same_end
    ldrh r0, [r7]
    ldrh r1, [r7, r8]
    cmp r0, r1
    bne sm_same_end
    adds r7, #2
    b sm_same_tail
sm_same_end:
    ldr r5, [sp, #8]
    subs r1, r7, r4
    lsrs r1, r1, #1
    cmp r1, #2
    blo sm_changed                  @ one pixel as before: cheaper inside a literal
    movw r2, #MAX_SKIP
sm_skips:
    mov r0, r1
    cmp r0, r2
    it hi
    movhi r0, r2
    subs r1, r1, r0
    orr r0, r0, #SKIP
    strh r0, [r6], #2
    cmp r1, #0
    bne sm_skips
    mov r4, r7
    b sm_next
sm_changed:
    adds r3, r4, #4
    cmp r3, r5
    bhs sm_literal                  @ fewer than three left
    ldrh r0, [r4]
    ldrh r1, [r4, #2]
    cmp r0, r1
    bne sm_literal
    ldrh r1, [r4, #4]
    cmp r0, r1
    bne sm_literal
    adds r7, r4, #6                 @ a run: as far as it goes, two pixels a word where it can
    movw r10, #MAX_RUN_BYTES
    add r10, r4
    cmp r10, r5
    it hi
    movhi r10, r5
    orr r3, r0, r0, lsl #16
    tst r7, #2
    beq sm_run_words
    cmp r7, r10
    bhs sm_run_end
    ldrh r1, [r7]
    cmp r1, r0
    bne sm_run_end
    adds r7, #2
sm_run_words:
    adds r2, r7, #4
    cmp r2, r10
    bhi sm_run_tail
    ldr r1, [r7]
    cmp r1, r3
    bne sm_run_tail
    mov r7, r2
    b sm_run_words
sm_run_tail:
    cmp r7, r10
    bhs sm_run_end
    ldrh r1, [r7]
    cmp r1, r0
    bne sm_run_end
    adds r7, #2
    b sm_run_tail
sm_run_end:
    subs r1, r7, r4
    lsrs r1, r1, #1
    orr r1, r1, #RUN
    strh r1, [r6], #2
    strh r0, [r6], #2
sm_run_prev:
    strh r0, [r4, r8]
    adds r4, #2
    cmp r4, r7
    blo sm_run_prev
    b sm_next
sm_literal:                         @ up to three equal pixels, or two as before
    mov r10, r6                     @ its count's place
    adds r6, #2
    mov r7, r4
sm_literal_copy:
    ldrh r0, [r7]
    strh r0, [r7, r8]
    strh r0, [r6], #2
    adds r7, #2
    cmp r7, r5
    bhs sm_literal_end
    subs r1, r7, r4
    movw r2, #MAX_LITERAL_BYTES
    cmp r1, r2
    bhs sm_literal_end
    adds r3, r7, #4
    cmp r3, r5
    bhs sm_literal_same
    ldrh r0, [r7]
    ldrh r1, [r7, #2]
    cmp r0, r1
    bne sm_literal_same
    ldrh r1, [r7, #4]
    cmp r0, r1
    beq sm_literal_end
sm_literal_same:
    cmp r11, #0
    bne sm_literal_copy
    adds r3, r7, #2
    cmp r3, r5
    bhs sm_literal_copy
    ldrh r0, [r7]
    ldrh r1, [r7, r8]
    cmp r0, r1
    bne sm_literal_copy
    add r3, r7, r8
    ldrh r0, [r7, #2]
    ldrh r1, [r3, #2]
    cmp r0, r1
    bne sm_literal_copy
sm_literal_end:
    subs r1, r7, r4
    lsrs r1, r1, #1
    strh r1, [r10]
    mov r4, r7
    b sm_next
sm_coded:
    ldr r1, [sp]
    sub r0, r6, r1
    add sp, #12
    pop {r4-r11, pc}

.ltorg
.align 2
sm_seq:                             @ the last request's seq
    .space 4
sm_trailer:
    .space TRAILER
sm_events_sent:                     @ sm_events' count at the last reply
    .space 4
sm_events:                          @ the events ever logged, then RING records {µs, event}
    .space 4 + RING * EVENT
sm_prev:                            @ the frame as the host has it
    .space FB_BYTES
sm_out:                             @ right after sm_prev; at most a halfword a pixel and a count, then the events
    .space FB_BYTES + 16 + 4 + RING * EVENT + 4 * LEDS
