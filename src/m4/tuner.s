@ tuner.s - Tuner Activation and Lock Tuner Settings on a page of the tuner's settings, shown third; tools/features/tuner.py places the hooks.
.syntax unified
.thumb
.include "hxtra.inc"
.equ PAGE, 4                        @ its page at [view+0x74], after the stock ones; tools/features/tuner.py's PAGE
.equ SHOWN_AT, 2                    @ its place in the order the pages are paged and dotted; tools/features/tuner.py's SHOWN_AT
.equ STOCK_PAGES, 4
.equ KNOBS, 2                       @ knob 2 of this page is empty
.equ PRESS, 1                       @ Tuner Activation's Press
.equ GUARD, 0x28d96135              @ (5) -> 0 when the tuner may open, as the stock hold of TAP asks
.equ REQUEST_TUNER, 0x28d96589
.equ TAP_CORE, 0x28d9bfa9
.equ TURN_FN_CONT, 0x28d916d9       @ the knob handler after its prologue, which tuner_turn_hook runs itself
.equ RESET_RET, 0x28d9176f          @ the event handler's pop {r3,r4,r5,pc}
.equ PAINT, 0x28dcca61              @ (view): takes the widget lock itself
.equ PAINT_TBH, 0x28dcca93
.equ PAINT_END, 0x28dccb65
.equ STEPS, 0x28dfe2d9              @ (raw knob delta) -> detents
.equ SHOW, 0x28dc6599               @ (knob, shown)
.equ VALUE_TEXT, 0x28dc654d         @ (knob, text)
.equ POSITION, 0x28dc648d           @ (knob, 0.0f..1.0f)
.equ LABEL, 0x28dc63d1              @ (knob, text)
.equ NEXT_CONT, 0x28d91785
.equ PREV_CONT, 0x28d917c7
.equ STORE_CONT, 0x28d917cf
.equ DOTS_CONT, 0x28dccd57

.macro SHOWN reg                    @ \reg a page -> its place in the order
    cmp \reg, #PAGE
    beq 1f
    cmp \reg, #SHOWN_AT
    it hs
    addhs \reg, #1
    b 2f
1:  movs \reg, #SHOWN_AT
2:
.endm

.thumb_func
tuner_tap:                          @ in place of the TAP/Tunr tap's tail call of the tap core: in Press mode a tuner request instead
    push {r0-r4, lr}
    movs r0, #SETTING_TUNER_ACTIVATE
    movs r1, #SETTING_TUNER_ACTIVATE_MAX
    movs r2, #SETTING_TUNER_ACTIVATE_DEFAULT
    bl hxtra_setting_get
    cmp r0, #PRESS
    bne tap_stock
    movs r0, #5
    ldr r3, =GUARD
    blx r3
    cmp r0, #0
    bne tap_out
    ldr r3, =REQUEST_TUNER
    blx r3
tap_out:
    add sp, #16
    pop {r4, pc}
tap_stock:
    pop {r0-r4, lr}
    ldr pc, =TAP_CORE

.thumb_func
tuner_turn_hook:                    @ at the knob handler's start (r0 the event, r1 the view): the stock runs unless tuner_turn returns 1
    push {r0-r2, lr}
    bl tuner_turn
    mov r3, r0
    pop {r0-r2, lr}
    cmp r3, #0
    bne turn_hook_out
    push {r3-r7, lr}                @ the stock prologue the hook's b.w took
    ldrb r6, [r0, #1]
    ldr pc, =TURN_FN_CONT
turn_hook_out:
    bx lr

.macro RESET knob, cont
.thumb_func
tuner_reset\knob:                   @ the event handler's reset of a knob (r4 the view): the stock runs unless tuner_press returns 1
    mov r0, r4
    movs r1, #\knob
    bl tuner_press
    mov r1, r4
    cmp r0, #0
    bne 1f
    ldrb r3, [r1, #0x74]            @ the stock instruction the hook's b.w took
    ldr pc, =\cont
1:  ldr pc, =RESET_RET
.endm
RESET 0, 0x28d91859
RESET 1, 0x28d91843
RESET 2, 0x28d917ff

.thumb_func
tuner_next_page:                    @ in place of the next-page case's read of the page (the view in r1): r3 its place in the order
    ldrb r3, [r1, #0x74]
    SHOWN r3
    ldr pc, =NEXT_CONT

.thumb_func
tuner_prev_page:                    @ in place of the previous-page case's read of the page (the view in r1): r3 its place in the order
    ldrb r3, [r1, #0x74]
    SHOWN r3
    ldr pc, =PREV_CONT

.thumb_func
tuner_store_page:                   @ before the page change's store (r3 the new place in the order): r3 the page shown there
    cmp r3, #SHOWN_AT
    beq 1f
    it hi
    subhi r3, #1
    b 2f
1:  movs r3, #PAGE
2:  movs r5, #1                     @ the stock instructions the hook's b.w took
    mov r0, r4
    ldr pc, =STORE_CONT

.thumb_func
tuner_dots:                         @ in place of the page dots' read of the page (the view in r4): r0 its place in the order
    ldrb r0, [r4, #0x74]
    SHOWN r0
    ldr pc, =DOTS_CONT

.thumb_func
tuner_switch:                       @ in place of the paint's switch on the page (r3, the view in r4): page 4 to tuner_paint
    cmp r3, #PAGE
    beq switch_mine
    cmp r3, #STOCK_PAGES - 1
    bhi switch_end
    ldr pc, =PAINT_TBH
switch_mine:
    mov r0, r4
    bl tuner_paint
switch_end:
    ldr pc, =PAINT_END

.thumb_func
tuner_turn:                         @ r0 a knob turn {-, knob, -, -, delta}, r1 the view -> r0 1 when the stock must not run
    push {r4-r6, lr}
    ldrb r2, [r1, #0x74]
    cmp r2, #PAGE
    bne locked
    mov r6, r1
    ldrb r4, [r0, #1]
    cmp r4, #2                      @ the stock counts detents of knobs 0..2 only
    bhi handled
    ldr r0, [r0, #4]
    ldr r3, =STEPS
    blx r3
    mov r5, r0
    cmp r4, #KNOBS
    bhs handled
    mov r0, r4
    bl knob_get
    adr r3, knobs
    add.w r3, r3, r4, lsl #2
    ldrb r2, [r3, #2]
    adds r1, r0, r5
    it lt
    movlt r1, #0
    cmp r1, r2
    it gt
    movgt r1, r2
    cmp r1, r0
    beq handled
    b changed

.thumb_func
tuner_press:                        @ r0 the view, r1 the knob pressed -> r0 1 when the stock reset must not run
    push {r4-r6, lr}
    ldrb r2, [r0, #0x74]
    cmp r2, #PAGE
    bne locked
    mov r6, r0
    mov r4, r1
    cmp r4, #KNOBS
    bhs handled
    mov r0, r4
    bl knob_get
    adr r3, knobs
    add.w r3, r3, r4, lsl #2
    ldrb r1, [r3, #3]
    cmp r0, r1
    beq handled
changed:                            @ r4 the knob, r1 its new value, r6 the view
    mov r0, r4
    bl knob_set
    mov r0, r6
    ldr r3, =PAINT
    blx r3
handled:
    movs r0, #1
    pop {r4-r6, pc}
locked:                             @ off page 4, Lock On keeps the stock from changing a setting; page 4 stays open so Lock can go Off
    movs r0, #1
    bl knob_get
    pop {r4-r6, pc}

.thumb_func
tuner_paint:                        @ r0 the view, inside its paint: page 4's knobs, and knob 2 hidden
    push {r4-r6, lr}
    movs r5, #0
paint_knob:
    mov r0, r5
    movs r1, #1
    ldr r3, =SHOW
    blx r3
    mov r0, r5
    bl knob_get
    mov r4, r0
    mov r0, r5
    adr r1, values
    add.w r1, r1, r5, lsl #5
    add.w r1, r1, r4, lsl #4
    ldr r3, =VALUE_TEXT
    blx r3
    mov r0, r5
    ldr r1, =0x3f800000             @ 1.0f, times the value: the knob turned fully on its last value
    muls r1, r4
    ldr r3, =POSITION
    blx r3
    mov r0, r5
    adr r1, labels
    add.w r1, r1, r5, lsl #4
    ldr r3, =LABEL
    blx r3
    adr r6, colours
paint_colour:
    mov r0, r5
    ldr r1, [r6, #4]
    ldr r3, [r6]
    blx r3
    adds r6, #8
    adr r3, colours_end
    cmp r6, r3
    bne paint_colour
    adds r5, #1
    cmp r5, #KNOBS
    bne paint_knob
    movs r0, #KNOBS
    movs r1, #0
    ldr r3, =SHOW
    blx r3
    pop {r4-r6, pc}

knob_get:                           @ r0 knob 0..1 -> r0 its setting's value
    adr r3, knobs
    add.w r3, r3, r0, lsl #2
    ldrh r0, [r3]
    ldrb r1, [r3, #2]
    ldrb r2, [r3, #3]
    b hxtra_setting_get

knob_set:                           @ r0 knob 0..1, r1 its setting's new value, stored as an int
    adr r3, knobs
    ldrh.w r0, [r3, r0, lsl #2]
    b hxtra_setting_set

.ltorg
.balign 4
knobs:                              @ per knob: ID, max, default
    .hword SETTING_TUNER_ACTIVATE
    .byte SETTING_TUNER_ACTIVATE_MAX, SETTING_TUNER_ACTIVATE_DEFAULT
    .hword SETTING_TUNER_LOCK
    .byte SETTING_TUNER_LOCK_MAX, SETTING_TUNER_LOCK_DEFAULT
colours:                            @ (function, colour) as the stock paints a knob that can be turned
    .word 0x28dc6455, 0xffffff
    .word 0x28dc651d, 0x6b6b6b
    .word 0x28dc6535, 0x4d4d4d
    .word 0x28dc6505, 0xb1b1b1
    .word 0x28dc6569, 0xb1b1b1
colours_end:
.balign 16, 0
labels:                             @ per knob, 16 bytes: tools/features/tuner.py's labels
    .asciz "Activate"
    .balign 16, 0
    .asciz "Lock"
    .balign 16, 0
values:                             @ per knob, 32 bytes: its two values, 16 bytes each
    .asciz "Hold"
    .balign 16, 0
    .asciz "Press"
    .balign 16, 0
    .asciz "Off"
    .balign 16, 0
    .asciz "On"
    .balign 16, 0

HXTRA_SETTING_GET
HXTRA_SETTING_SET
