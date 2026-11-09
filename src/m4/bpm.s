@ bpm.s - the tempo as text at the top left of the Home screen, in the font and colour BPM Font and BPM Color say, and a 30 px dot
@ lit in that colour while the TAP footswitch's ring is, red on a tap, left or right of the preset number (or both) as BPM Dot Pos says.
@ The tempo is the Global Setting the stock code uses, Global BPM or Preset BPM as Tempo Select says, as a whole BPM, with " X" while
@ the tempo screen would show Extrnl. tools/features/bpm.py chains the handlers; only bpm_ledsend is a hook of its own.
.syntax unified
.thumb
.include "customos.inc"
.equ BPM_DOTS, 18                   @ rectangles: 9 a dot
.equ BPM_DOT_TOP, 237               @ the dots' top (y counts up from the bottom)
.equ FS_FUNCTIONS, 0x28128a74       @ each footswitch's function, two bytes apart: 1 is TAP

bpm_written:                        @ after the settings store's write (ID, value, how): the Home view only repaints on request
    subs r0, #14                    @ Tempo Select, Global BPM, Preset BPM
    cmp r0, #2
    bls bpm_repaint
    bx lr

bpm_repaint:                        @ a repaint, once the Home view has painted: the UI may not be up before
    adr.w r0, bpm_data
    ldr r0, [r0]
    cbz r0, bpm_unpainted
    movs r0, #0
    movs r1, #1
    ldr r3, =0x28db8509             @ the redraw request the layout code ends with: (0, 1)
    bx r3
bpm_unpainted:
    bx lr

bpm_ledsend:                        @ the LED send's first two instructions, moved here after noting each footswitch ring lit or not
    push {lr}
    cmp r0, #2
    bhi bpm_sent
    lsls r2, r1, #8                 @ the colour is the low three bytes, black for off
    it ne
    movne r2, #1
    adr.w r3, bpm_rings
    strb r2, [r3, r0]
    cbz r2, bpm_sent
    ldr r3, =FS_FUNCTIONS
    ldrb.w r2, [r3, r0, lsl #1]
    cmp r2, #1
    bne bpm_sent
    adr.w r3, bpm_data
    ldrb r2, [r3, #6]
    cmp r2, #0
    it eq
    moveq r1, #0                    @ Tap Tempo LED is off: the ring stays dark, though the stock blinks it for the dot
bpm_sent:
    ldr r3, =0x281c90a4
    ldr r12, =0x28d98f79            @ the send after them; it sets r2 before it reads it
    bx r12

bpm_tick:                           @ after the LED task's 1 ms sleep: the dot lit as the TAP footswitch's ring is
    push {r4, lr}
    adr.w r4, bpm_data
    ldr r0, [r4]
    cmp r0, #0
    beq bpm_ticked
    ldr r0, [r4, #8]
    movw r1, #1500
    cmp r0, r1
    bhs bpm_booted
    adds r0, #1
    str r0, [r4, #8]
    movs r1, #20
    udiv r2, r0, r1
    mls r0, r2, r1, r0
    cmp r0, #0
    it eq
    bleq bpm_repaint                @ every 20 ms for 1.5 s from the first paint: the boot leaves black bars over the text [verified on unit]
bpm_booted:
    ldr r1, =FS_FUNCTIONS
    movs r2, #0
bpm_findtap:
    ldrb.w r0, [r1, r2, lsl #1]
    cmp r0, #1
    beq bpm_tapring
    adds r2, #1
    cmp r2, #3
    bne bpm_findtap
    ldr r0, [r4, #16]               @ no TAP footswitch (Preset, Snapshot modes): the stock beat stops, so the dot keeps it itself
    cbz r0, bpm_ticked
    ldr r3, =0x28da6459             @ the µs clock the stock beat runs on
    blx r3
    ldr r2, [r4, #16]
    ldr r1, [r4, #12]
    subs r1, r0, r1
    movw r3, #1000
    udiv r1, r1, r3
    cmp r1, r2
    bhi bpm_restart
    cmp.w r1, r2, lsr #1            @ the stock's test: over half a period, in whole ms
    bls bpm_ticked
    mul r2, r2, r3
    ldr r1, [r4, #12]
    add.w r1, r1, r2, lsr #1
    str r1, [r4, #12]
    ldrb r0, [r4, #4]
    eor r0, r0, #1
    b bpm_turn
bpm_restart:                        @ over a beat since the last turn (none seen since boot, or the tempo fell): the beat starts now
    str r0, [r4, #12]
    b bpm_ticked
bpm_tapring:
    adr.w r1, bpm_rings
    ldrb r0, [r1, r2]
    ldrb r1, [r4, #4]
    cmp r0, r1
    beq bpm_ticked
    ldr r1, =0x281cd074             @ the stock beat's last turn (µs): the dot carries on from it once no footswitch is TAP
    ldr r1, [r1]
    str r1, [r4, #12]
bpm_turn:
    strb r0, [r4, #4]
    movs r0, #0
    strb r0, [r4, #5]               @ a tap's red lasts until the ring's next turn
    bl bpm_repaint
bpm_ticked:
    pop {r4, pc}

bpm_tapled:                         @ after GET_VALUE(26, out) where the stock decides to blink: the real Tap Tempo LED kept, On returned
    ldr r0, [r1, #4]
    adr.w r2, bpm_data
    strb r0, [r2, #6]
    movs r0, #1
    str r0, [r1, #4]
    bx lr

bpm_tap:                            @ before the tap tempo core: the dot lit red at once
    adr.w r0, bpm_data
    movs r1, #1
    strb r1, [r0, #4]
    strb r1, [r0, #5]
    b bpm_repaint

bpm_construct:                      @ after the Home view's constructor: the widgets, hidden until the first paint
    push {r4, r5, r6, lr}
    adr.w r4, bpm_widget
    mov r0, r4
    adr.w r1, bpm_node
    ldr r3, =0x28e249d1             @ init(widget, node)
    blx r3
    mov r0, r4
    movs r1, #2
    movs r2, #238                   @ y counts up from the bottom
    ldr r3, =0x28e24a69             @ setPos
    blx r3
    mov r0, r4
    movs r1, #6                     @ 3 * row + column: row 2 puts y at the top, column 0 x at the left
    ldr r3, =0x28e24ac9             @ setAnchor
    blx r3
    mov r0, r4
    movs r1, #2
    ldr r3, =0x28e249e9             @ setFont
    blx r3
    mov r0, r4
    adr.w r1, bpm_text
    movs r2, #16
    ldr r3, =0x28e24bc1             @ setText
    blx r3
    mov r0, r4
    movs r1, #0
    ldr r3, =0x28e24bc9             @ setVisible
    blx r3
    adr.w r4, bpm_dot
    adr.w r5, bpm_dotnodes
    mov r6, r5
bpm_dotmake:
    mov r0, r4
    mov r1, r5
    ldr r3, =0x28e24989             @ init(widget, node)
    blx r3
    mov r0, r4
    movs r1, #6                     @ placed by the top left corner, as the text
    ldr r3, =0x28e24a19
    blx r3
    mov r0, r4
    movs r1, #0
    ldr r3, =0x28e24b01             @ setVisible
    blx r3
    adds r4, #0x1c
    adds r5, #0x28
    cmp r4, r6
    bne bpm_dotmake
    pop {r4, r5, r6, pc}

bpm_before:                         @ before the Home paint (framebuffer, Home view): the settings and the tempo into the widgets, then the erase pass
    push {r3-r9, lr}
    mov r8, r0
    adr.w r0, bpm_data
    movs r1, #1
    str r1, [r0]
    movs r0, #SETTING_BPM_DOT
    movs r1, #SETTING_BPM_DOT_MAX
    movs r2, #SETTING_BPM_DOT_DEFAULT
    bl customos_setting_get
    add.w r9, r0, #1                @ the dots shown: 1 left, 2 right, 3 both
    movs r0, #SETTING_BPM_FONT
    movs r1, #SETTING_BPM_FONT_MAX
    movs r2, #SETTING_BPM_FONT_DEFAULT
    bl customos_setting_get
    adr.w r1, bpm_fonts
    ldrb r5, [r1, r0]
    movs r0, #SETTING_BPM_COLOR
    movs r1, #SETTING_BPM_COLOR_MAX
    movs r2, #SETTING_BPM_COLOR_DEFAULT
    bl customos_setting_get
    adr.w r1, bpm_colours
    ldr.w r6, [r1, r0, lsl #2]
    mov r0, r5
    bl bpm_format
    adr.w r7, bpm_widget
    mov r0, r7
    mov r1, r5
    ldr r3, =0x28e249e9             @ setFont
    blx r3
    mov r0, r7
    mov r1, r6
    ldr r3, =0x28e24a29             @ setColor
    blx r3
    mov r0, r7
    adr.w r1, bpm_text
    movs r2, #16
    ldr r3, =0x28e24bc1             @ setText
    blx r3
    mov r0, r7
    movs r1, #1                     @ showing marks it dirty every paint, so it is redrawn whatever else repainted the Home view
    ldr r3, =0x28e24bc9             @ setVisible
    blx r3
    adr.w r1, bpm_data
    ldrb r0, [r1, #5]
    cmp r0, #0
    it ne
    movne r6, #0xff0000             @ tapped
    ldrb r0, [r1, #4]
    cmp r0, #0
    it eq
    ldreq r6, =0x404040             @ unlit
    adr.w r5, bpm_dotshape
    adr.w r7, bpm_dot
bpm_dotplace:                       @ placed before sized: a first erase then covers only the new place
    ldrb r0, [r5, #4]
    tst r0, r9
    beq bpm_dothide                 @ each dot has its own widgets: a move would erase the box spanning both places
    mov r0, r7
    ldrb r1, [r5, #0]
    ldrb r2, [r5, #1]
    rsb.w r2, r2, #BPM_DOT_TOP
    ldr r3, =0x28e24af1             @ setPos
    blx r3
    mov r0, r7
    ldrb r1, [r5, #2]
    ldrb r2, [r5, #3]
    ldr r3, =0x28e24b29             @ setSize
    blx r3
    mov r0, r7
    mov r1, r6
    ldr r3, =0x28e24b99             @ setColor
    blx r3
    movs r1, #1                     @ dirty every paint, as the text
    b bpm_dotshow
bpm_dothide:
    movs r1, #0
bpm_dotshow:
    mov r0, r7
    ldr r3, =0x28e24b01             @ setVisible
    blx r3
    adds r5, #6
    adds r7, #0x1c
    adr.w r0, bpm_dotnodes
    cmp r7, r0
    bne bpm_dotplace
    mov r0, r8
    ldr r3, =0x28e24c91             @ erase(context, context, widget) of a text widget
    bl bpm_each
    mov r0, r8
    ldr r3, =0x28e24b41             @ and of a rectangle
    bl bpm_doteach
    pop {r3-r9, pc}

bpm_after:                          @ after the Home paint (framebuffer): the draw pass
    push {r4, lr}
    mov r4, r0
    ldr r3, =0x28e24c31             @ draw(context, context, widget) of a text widget
    bl bpm_each
    mov r0, r4
    ldr r3, =0x28e24b59             @ and of a rectangle
    bl bpm_doteach
    pop {r4, pc}

bpm_each:                           @ r0 the context, r3 a function (context, context, widget) for the text widget
    adr.w r1, bpm_widget
    movs r2, #1
    b bpm_foreach
bpm_doteach:                        @ the same for the dots' rectangles
    adr.w r1, bpm_dot
    ldr r2, =(0x1c << 16) | BPM_DOTS
bpm_foreach:                        @ r0 the context, r1 the first widget, r2 count | stride << 16, r3 the function: under the widget lock
    push {r4-r8, lr}
    mov r4, r0
    mov r5, r1
    uxth r6, r2
    lsrs r7, r2, #16
    mov r8, r3
    ldr r3, =0x28e24971             @ the widget lock, as the stock paint takes it
    blx r3
bpm_next:
    mov r0, r4
    mov r1, r4
    mov r2, r5
    blx r8
    add r5, r7
    subs r6, #1
    bne bpm_next
    ldr r3, =0x28e24ae9
    blx r3
    pop {r4-r8, pc}

bpm_get:                            @ r0 a stock setting ID -> r0 its value as stored (a float for the BPM), -1 if it has none
    push {r4, lr}
    sub sp, #8
    mov r1, sp
    ldr r3, =0x28e1f845             @ GET_VALUE(id, out): the value at out + 4
    blx r3
    cmp r0, #0
    ldr r0, [sp, #4]
    it lt
    movlt r0, #-1
    add sp, #8
    pop {r4, pc}

bpm_format:                         @ r0 a font -> bpm_text holds the tempo, or -- if there is none
    push {r4-r7, lr}
    mov r7, r0
    movs r0, #14                    @ Tempo Select: Global BPM when Global, else Preset BPM, as the stock code picks
    bl bpm_get
    cmp r0, #2
    ite eq
    moveq r0, #15
    movne r0, #16
    bl bpm_get
    adr.w r4, bpm_text
    movs r6, #0
    strb r6, [r4]
    adr.w r3, bpm_data
    str r6, [r3, #16]
    ubfx r2, r0, #23, #8
    subs r2, #127
    cmp r2, #9
    bhi bpm_none                    @ not 1..1023: no tempo (unsigned, so negative exponents too)
    vmov s15, r0
    ldr r1, =0x476a6000             @ 60000.0f: the period in whole ms, as the stock works it out (0x28dd0af6)
    vmov s14, r1
    vdiv.f32 s15, s14, s15
    vcvt.u32.f32 s15, s15
    vstr s15, [r3, #16]
    ubfx r1, r0, #0, #23
    orr r1, r1, #0x800000
    movs r3, #10
    mul r1, r1, r3
    rsb.w r2, r2, #23
    subs r3, r2, #1
    movs r0, #1
    lsls r0, r3
    add r1, r0
    lsrs r1, r2                     @ the tempo in tenths, rounded
    adds r1, #5
    movs r3, #10
    udiv r1, r1, r3                 @ the whole BPM, below 1000
    movs r5, #100
    udiv r2, r1, r5
    mls r1, r2, r5, r1
    movs r5, #10
    udiv r3, r1, r5
    mls r1, r3, r5, r1
    cbz r2, bpm_tens
    adds r2, #'0'
    strb r2, [r4], #1
    b bpm_tens_digit
bpm_tens:
    cbz r3, bpm_ones
bpm_tens_digit:
    adds r3, #'0'
    strb r3, [r4], #1
bpm_ones:
    adds r1, #'0'
    strb r1, [r4], #1
    cbz r7, bpm_end                 @ 21 Bold and 35 Bold have digits only
    cmp r7, #4
    beq bpm_end
    ldr r3, =0x28d9685d             @ the flag the tempo screen shows Extrnl for, and taps are ignored by
    blx r3
    cbz r0, bpm_end
    movs r0, #' '
    strb r0, [r4], #1
    movs r0, #'X'
    strb r0, [r4], #1
bpm_end:
    movs r0, #0
    strb r0, [r4]
    pop {r4-r7, pc}
bpm_none:                           @ the digit-only fonts have no dash: nothing
    cmp r7, #0
    beq bpm_end
    cmp r7, #4
    beq bpm_end
    movs r0, #'-'
    strb r0, [r4], #1
    strb r0, [r4], #1
    b bpm_end

CUSTOMOS_SETTING_GET
.ltorg
.balign 4
bpm_colours:                        @ BPM Color: White, Gray, Red, Orange, Yellow, Green, Cyan, Blue, Purple
    .word 0xffffff, 0xb1b1b1, 0xff0000, 0xff7f00, 0xffff00, 0x00ff00, 0x00ffff, 0x0080ff, 0xb000ff
bpm_fonts:                          @ BPM Font: 41 Lite, 35 Bold, 28 Bold, 28 Lite, 21 Bold, 21 Reg, as font numbers
    .byte 5, 4, 2, 3, 0, 1
.balign 4
bpm_dotshape:                       @ x, y below the dots' top, w, h, BPM Dot Pos bit, 0: nested rectangles whose union is a 30 px circle
    .byte 80, 0, 8, 30, 1, 0        @ left: the right one mirrored about the preset number's middle, x = 160
    .byte 77, 1, 14, 28, 1, 0
    .byte 76, 2, 16, 26, 1, 0
    .byte 74, 3, 20, 24, 1, 0
    .byte 73, 4, 22, 22, 1, 0
    .byte 72, 5, 24, 20, 1, 0
    .byte 71, 7, 26, 16, 1, 0
    .byte 70, 8, 28, 14, 1, 0
    .byte 69, 11, 30, 8, 1, 0
    .byte 232, 0, 8, 30, 2, 0       @ right, from x = 221 [verified on unit]
    .byte 229, 1, 14, 28, 2, 0
    .byte 228, 2, 16, 26, 2, 0
    .byte 226, 3, 20, 24, 2, 0
    .byte 225, 4, 22, 22, 2, 0
    .byte 224, 5, 24, 20, 2, 0
    .byte 223, 7, 26, 16, 2, 0
    .byte 222, 8, 28, 14, 2, 0
    .byte 221, 11, 30, 8, 2, 0
.balign 4
bpm_data:                           @ 0 painted, 4 dot lit, 5 tapped red, 6 Tap Tempo LED on, 8 ms since first paint, 12 last turn (µs), 16 period (ms)
    .word 0, 0x00010000, 0, 0, 0
bpm_rings:                          @ each footswitch ring lit, as last sent
    .space 4
bpm_text:
    .space 16
bpm_widget:
    .space 0x30
bpm_node:
    .space 0x28
bpm_dot:                            @ rectangle widgets, as bpm_dotshape
    .space BPM_DOTS * 0x1c
bpm_dotnodes:
    .space BPM_DOTS * 0x28
