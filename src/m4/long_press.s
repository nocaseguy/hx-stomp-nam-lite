@ long_press.s - long-press footswitch actions: in Stomp mode, a latching stomp footswitch 1..3 with a Hold action set acts on release
@ when tapped (its press is held back and replayed on the click) and runs the action when held for 1 s: the tuner, or a press of FS4/FS5.
@ tools/features/long_press.py owns the footswitch event handler 0x28dd1978 and enters lp_event with the stock handler in r2.
.syntax unified
.thumb
.include "customos.inc"
.equ PRESS, 1
.equ RELEASE, 2
.equ CLICK, 3                       @ a release before a hold, posted after the release
.equ HOLD, 5
.equ FS1_CODE, 12                   @ footswitches 1..5 are key codes 12..16
.equ STOMP, 2                       @ the footswitch function that toggles blocks

.thumb_func
lp_event:                           @ r0 event {1 key, code, -, -, type}, r1 the handler's object, r2 the stock handler
    push {r4-r8, lr}
    sub sp, #8
    mov r4, r0
    mov r5, r1
    mov r6, r2
    ldrb r0, [r4]
    cmp r0, #1
    bne pass
    ldrb r7, [r4, #1]
    subs r7, #FS1_CODE
    cmp r7, #3
    bhs pass
    adr.w r8, pending
    ldr r0, [r4, #4]
    cmp r0, #PRESS
    beq press
    cmp r0, #CLICK
    beq click
    cmp r0, #HOLD
    bne pass
    ldrb.w r0, [r8, r7]
    cmp r0, #0
    beq pass
    movs r0, #0
    strb.w r0, [r8, r7]
    mov r0, r7
    bl action_of
    cmp r0, #1
    beq tuner
    bhi other_switch
    add.w r0, r7, #FS1_CODE         @ no action any more (the mode changed while held): the held-back press after all
    bl replay
    b out
other_switch:
    adds r0, #13                    @ 2 FS4, 3 FS5: codes 15, 16
    bl replay
    b out
tuner:                              @ as the stock hold of TAP does it
    movs r0, #5
    ldr r3, =0x28d96135
    blx r3
    cmp r0, #0
    bne out
    ldr r3, =0x28d96589
    blx r3
    b out
press:
    mov r0, r7
    bl action_of
    cmp r0, #0
    it ne
    movne r0, #1
    strb.w r0, [r8, r7]
    cmp r0, #0
    beq pass
    b out
click:
    ldrb.w r0, [r8, r7]
    cmp r0, #0
    beq pass
    movs r0, #0
    strb.w r0, [r8, r7]
    add.w r0, r7, #FS1_CODE
    bl replay
    b out
pass:
    mov r0, r4
    mov r1, r5
    blx r6
out:
    add sp, #8
    pop {r4-r8, pc}

replay:                             @ r0 a footswitch code: its press, then its release, through the stock handler (r5 its object, r6 it)
    push {r7, lr}
    sub sp, #8
    movs r1, #1
    strb r1, [sp]
    strb r0, [sp, #1]
    movs r1, #0
    strh r1, [sp, #2]
    movs r1, #PRESS
    str r1, [sp, #4]
    mov r0, sp
    mov r1, r5
    blx r6
    movs r1, #RELEASE
    str r1, [sp, #4]
    mov r0, sp
    mov r1, r5
    blx r6
    add sp, #8
    pop {r7, pc}

.thumb_func
lp_boot:                            @ after the Home constructor at boot: a Hold setting whose stored record is not an int (type 2) becomes one
    push {r4, r5, lr}               @ an ID with stock bool limits keeps type 1 in its record and the menu then offers only two values
    sub sp, #20                     @ 0 GET_VALUE's out, 8 the record to write {type, -, -, -, value}
    movs r4, #0
boot_next:
    adr r3, hold_ids
    ldrh.w r5, [r3, r4, lsl #1]
    mov r0, r5
    mov r1, sp
    ldr r3, =0x28e1f845
    blx r3
    cmp r0, #0
    blt boot_skip
    ldrb r0, [sp]
    cmp r0, #2
    beq boot_skip
    ldr r0, [sp, #4]
    cmp r0, #SETTING_LONG_PRESS_FS1_MAX
    it hi
    movhi r0, #SETTING_LONG_PRESS_FS1_DEFAULT
    str r0, [sp, #12]
    movs r0, #2
    str r0, [sp, #8]
    ldr r3, =0x28e007ed             @ the setter's context, as the stock footswitch-mode writes take it
    blx r3
    mov r1, r5
    add r2, sp, #8
    movs r3, #6
    ldr.w r12, =0x28e1f8f5          @ the setter (context, ID, record, how): stores the record's type and value
    blx r12
boot_skip:
    adds r4, #1
    cmp r4, #3
    bne boot_next
    add sp, #20
    pop {r4, r5, pc}

action_of:                        @ r0 footswitch 0..2 -> r0 its Hold action (1 Tuner, 2 FS4, 3 FS5), or 0 where the stock behaviour stays
    push {r4, r5, lr}
    sub sp, #12                     @ GET_VALUE's out, the value at +4
    mov r4, r0
    adr r3, hold_ids
    ldrh.w r0, [r3, r4, lsl #1]
    movs r1, #SETTING_LONG_PRESS_FS1_MAX
    movs r2, #SETTING_LONG_PRESS_FS1_DEFAULT
    bl customos_setting_get
    movs r5, r0
    beq none
    movs r0, #21                    @ Footswitch Mode: 2 and 3 are the preset and snapshot modes
    mov r1, sp
    ldr r3, =0x28e1f845
    blx r3
    cmp r0, #0
    blt mode_ok
    ldr r0, [sp, #4]
    subs r0, #2
    cmp r0, #1
    bls none
mode_ok:
    ldr r3, =0x28128a74             @ footswitch k's function, at +2k
    ldrb.w r0, [r3, r4, lsl #1]
    cmp r0, #STOMP
    bne none
    ldr r3, =0x28d96085             @ the bypass assignment lists
    blx r3
    mov r1, r4
    ldr r3, =0x28dd83c5             @ momentary: its release toggles too, so a held-back press would break it
    blx r3
    cmp r0, #0
    bne none
    mov r0, r5
    b action_out
none:
    movs r0, #0
action_out:
    add sp, #12
    pop {r4, r5, pc}

.ltorg
.balign 2
hold_ids:
    .hword SETTING_LONG_PRESS_FS1, SETTING_LONG_PRESS_FS2, SETTING_LONG_PRESS_FS3
.balign 4
pending:                            @ per footswitch 0..2: its press was held back
    .space 4

CUSTOMOS_SETTING_GET
