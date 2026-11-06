@ long_press.s - long-press footswitch actions: in Stomp mode, a latching stomp footswitch 1..5 with a Hold action set acts on release
@ when tapped (its press is held back and replayed on the click) and runs the action when held for 1 s: the tuner, a press of FS4/FS5,
@ or a virtual footswitch FS6..FS10, which toggles the blocks assigned to MIDI CC 20..24 (Bypass Assign > MIDI In).
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
.equ SWITCHES, 5                    @ footswitches 1..5, 4 and 5 the external pair
.equ VIRTUAL, 4                     @ Hold values 4..8 are FS6..FS10
.equ VIRTUAL_CC, 20                 @ FS6's MIDI CC; tools/features/long_press.py's VIRTUAL_CC
.equ CONTROLLERS, 0x28d9608d        @ () -> the parameter controllers; +4 their lock, 64 nodes of 0x48 bytes from +0xac
.equ MIDI_CC, 8                     @ the MIDI CC controller

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
    cmp r7, #SWITCHES
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
    cmp r0, #VIRTUAL
    bhs virtual_switch
    cmp r0, #1
    bhi other_switch
    add.w r0, r7, #FS1_CODE         @ no action any more (the mode changed while held): the held-back press after all
    bl replay
    b out
other_switch:
    adds r0, #13                    @ 2 FS4, 3 FS5: codes 15, 16
    bl replay
    b out
virtual_switch:
    subs r0, #VIRTUAL
    bl toggle_cc
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
lp_boot:                            @ after the Home constructor at boot: on the first boot, every Hold setting gets its default as an int (type 2)
    push {r4, r5, lr}               @ the stock records of these IDs hold in-range values (and some type 1, which the menu shows as two values),
    sub sp, #20                     @ so a record that is not yet an int marks the first boot. 0 GET_VALUE's out, 8 the record {type, -, -, -, value}
    movs r4, #0
boot_check:
    adr r3, hold_ids
    ldrh.w r0, [r3, r4, lsl #1]
    mov r1, sp
    ldr r3, =0x28e1f845
    blx r3
    cmp r0, #0
    blt boot_first
    ldrb r0, [sp]
    cmp r0, #2
    bne boot_first
    adds r4, #1
    cmp r4, #SWITCHES
    bne boot_check
    b boot_out
boot_first:
    movs r4, #0
boot_next:
    adr r3, hold_ids
    ldrh.w r5, [r3, r4, lsl #1]
    movs r0, #2
    str r0, [sp, #8]
    adr r3, hold_defaults
    ldrb r0, [r3, r4]
    str r0, [sp, #12]
    ldr r3, =0x28e007ed             @ the setter's context, as the stock footswitch-mode writes take it
    blx r3
    mov r1, r5
    add r2, sp, #8
    movs r3, #6
    ldr.w r12, =0x28e1f8f5          @ the setter (context, ID, record, how): stores the record's type and value
    blx r12
    adds r4, #1
    cmp r4, #SWITCHES
    bne boot_next
boot_out:
    add sp, #20
    pop {r4, r5, pc}

toggle_cc:                          @ r0 virtual footswitch 0..4: its blocks on MIDI CC 20 + r0 go to the opposite of the first one's state
    push {r4-r8, lr}
    sub sp, #8                      @ 0 the bypass the getter writes
    mov r8, r0
    add.w r4, r0, #VIRTUAL_CC
    ldr r3, =CONTROLLERS
    blx r3
    mov r5, r0
    adds r0, r5, #4
    ldr r3, =0x28e24c01             @ the controllers' lock, as the stock MIDI In lookup 0x28ddebcc takes it
    blx r3
    mvn r6, #0                      @ the first block on the CC, -1 for none
    add.w r3, r5, #0xac
    movs r2, #64
scan:
    ldrb r1, [r3, #0x44]
    cmp r1, #0x40                   @ a free node
    beq scan_next
    ldrb r1, [r3, #0x28]
    cmp r1, #2                      @ a bypass assignment
    bne scan_next
    ldrb r1, [r3, #0x10]
    cmp r1, #MIDI_CC
    bne scan_next
    ldr r1, [r3, #0x14]
    cmp r1, r4
    bne scan_next
    ldr r6, [r3, #0x2c]
    b scanned
scan_next:
    adds r3, #0x48
    subs r2, #1
    bne scan
scanned:
    adds r0, r5, #4
    ldr r3, =0x28e24bb1
    blx r3
    movs r7, #0xff
    strb r7, [sp]
    adds r0, r6, #1
    beq stateless
    ldr r3, =0x28d92a99             @ the tone, as the stock toggle at 0x28d9489c reads a block's bypass
    blx r3
    mov r1, r6
    mov r2, sp
    ldr r3, =0x28e04515             @ (tone, block, &bypassed): takes the DSP-model lock itself; leaves it 0xff for no block
    blx r3
    ldrb r7, [sp]
stateless:
    adr r3, latched
    cmp r7, #0xff
    bne stated
    ldrb.w r7, [r3, r8]             @ no block to read (none assigned, or the DSP not ready): the last state sent, flipped
    eor r7, r7, #1
stated:
    strb.w r7, [r3, r8]             @ r7 1: they are bypassed, so turn them on
    mov r0, r5
    movs r1, #MIDI_CC
    mov r2, r4
    movs r3, #0
    cmp r7, #0
    it ne
    movtne r3, #0x3f80              @ 1.0f: on, as the stock MIDI receive sends CC values / 127.0
    ldr.w r12, =0x28dde409
    blx r12
    add sp, #8
    pop {r4-r8, pc}

action_of:                          @ r0 footswitch 0..4 -> r0 its Hold action (1 Tuner, 2 FS4, 3 FS5, 4..8 FS6..FS10), or 0 where the stock behaviour stays
    push {r4, r5, lr}
    sub sp, #12                     @ GET_VALUE's out, the value at +4
    mov r4, r0
    adr r3, hold_ids
    ldrh.w r0, [r3, r4, lsl #1]
    movs r1, #SETTING_LONG_PRESS_FS1_MAX
    adr r2, hold_defaults
    ldrb r2, [r2, r4]
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
    .hword SETTING_LONG_PRESS_FS1, SETTING_LONG_PRESS_FS2, SETTING_LONG_PRESS_FS3, SETTING_LONG_PRESS_FS4, SETTING_LONG_PRESS_FS5
.balign 4
hold_defaults:
    .byte SETTING_LONG_PRESS_FS1_DEFAULT, SETTING_LONG_PRESS_FS2_DEFAULT, SETTING_LONG_PRESS_FS3_DEFAULT
    .byte SETTING_LONG_PRESS_FS4_DEFAULT, SETTING_LONG_PRESS_FS5_DEFAULT
.balign 4
pending:                            @ per footswitch 0..4: its press was held back
    .space 8
latched:                            @ per virtual footswitch 0..4: 1 when the last value sent turned its blocks on
    .space 8

CUSTOMOS_SETTING_GET
