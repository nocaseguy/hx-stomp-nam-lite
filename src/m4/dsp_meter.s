@ dsp_meter.s - the per-block DSP usage meter: each block in the Edit view's signal-flow row shows its share of the DSP in per cent, in black,
@ and the top right corner shows their sum against what blocks may use (90% less the firmware's fixed 15%), as Global Settings > CustomOS > DSP Disp asks,
@ in a text widget of our own on the block title's baseline.
@ The Edit view's top half (0x281282f8) has eight block slots, image widgets at view+0x4a4+0x24k, hidden when empty.
@ DSP costs are the firmware's own, in hundredths of a per cent (the preset total adds 1500 and must stay within 9000).
@ The model browser (0x281299d0) lists five models a page, each with its category's icon: dsp_browser centres each model's cost in white between its icon and name.
@ tools/features/dsp_meter.py chains dsp_paint after the Edit view top half's stock paint and dsp_browser after the browser's; patch_menu.py assembles this at build time.
.syntax unified
.thumb
.include "customos.inc"
.equ BUDGET, 75                     @ per cent of the DSP blocks may use: the preset limit 9000 less its fixed 1500, in hundredths
.equ TOTAL_RIGHT, 316
.equ TOTAL_TOP, 228                 @ the title's baseline (its top 0xea less ink row 22) plus this font's ink row 16
.equ TOTAL_FONT, 1                  @ hx21_regularFont
.thumb_func
dsp_paint:                          @ r0 the framebuffer, r1 the Edit view's top half, after its stock paint
    push {r4-r7, lr}
    sub sp, #44                     @ 0 the eight slots' DSP costs (-1 for none), 32 the blocks' sum in per cent (-1 for none), 36 DSP Disp
    mov r4, r0
    mov r5, r1
    movs r6, #0
    mvn r0, #0
none:
    str.w r0, [sp, r6, lsl #2]
    adds r6, #1
    cmp r6, #9
    bne none
    ldr r7, =0x28449e78             @ the DSP model: block records of 0x54 bytes
    ldr r7, [r7]
    cmp r7, #0
    beq costed
    movs r0, #0
    ldr r3, =0x28e07845             @ its lock, as the stock block lookup 0x28e0fe94 takes it; never held with the widget lock
    blx r3
    movs r6, #0
cost:
    ldr r1, =0x2812c590             @ the slot model: the second row's categories at +0x3f
    adds r1, r1, r6
    ldrb r1, [r1, #0x3f]
    mov r0, r6
    cbz r1, first_row
    adds r0, #8                     @ the slot shows the second row's block, as the layout 0x28dc1a86 picks its image
first_row:
    bl cost_of
    str.w r0, [sp, r6, lsl #2]
    adds r6, #1
    cmp r6, #8
    bne cost
    movs r6, #0
    str r6, [sp, #32]
sum:                                @ each block rounded as shown, so the shown numbers add up to the sum
    mov r0, r6
    bl cost_of
    cmp r0, #0
    blt summed
    adds r0, #50
    movs r2, #100
    udiv r0, r0, r2
    ldr r1, [sp, #32]
    add r1, r0
    str r1, [sp, #32]
summed:
    adds r6, #1
    cmp r6, #16
    bne sum
    movs r0, #0
    ldr r3, =0x28e0785d
    blx r3
costed:
    movs r0, #SETTING_DSP_METER_DISP
    movs r1, #SETTING_DSP_METER_DISP_MAX
    movs r2, #SETTING_DSP_METER_DISP_DEFAULT
    bl customos_setting_get
    str r0, [sp, #36]
    ldr r3, =0x28e24971             @ the widget lock
    blx r3
    addw r5, r5, #0x4a4
    movs r6, #0
slot:                               @ all this is in the framebuffer only, so whatever the stock paint redrew or hid has lost it
    ldrb r0, [r5, #0x1d]
    cbz r0, next
    ldr r0, [r5]
    cmp r0, #0x67
    beq next                        @ image 0x67 is every state of an empty slot, i.e. the cursor for placing a block
    ldr.w r1, [sp, r6, lsl #2]
    cmp r1, #0
    blt next
    adds r1, #50
    movs r2, #100
    udiv r1, r1, r2
    mov r0, r5
    bl number
next:
    adds r5, #0x24
    adds r6, #1
    cmp r6, #8
    bne slot
    ldr r0, [sp, #32]
    ldr r1, [sp, #36]
    bl total
    ldr r3, =0x28e24ae9
    blx r3
    movs r0, #0
    add sp, #44
    pop {r4-r7, pc}

.equ MODELS, 2                      @ the browser's list level that shows models (0x28dc3424 fills it)
.equ ROWS, 5
.equ PITCH, 40
.equ NAMES_X, 60                    @ where dsp_meter.py moves the names (stock 44) to make room for the labels
.equ LABEL_TOP, 187                 @ the first row's digits, centred on its icon (y 194 down)
.equ LABEL_SCALE, 2
.thumb_func
dsp_browser:                        @ r0 the framebuffer, r1 the model browser, after its stock paint
    push {r4-r8, lr}
    sub sp, #8                      @ 0 the browser level, 4 a model's browser item, then its cost
    mov r4, r0
    mov r5, r1
    ldrb r2, [r1, #0x40]
    cmp r2, #MODELS
    beq models
    adr.w r3, drawn                 @ no widget covers the labels, so leaving the model list must wipe them
    ldr r2, [r3]
    cmp r2, #0
    beq browser_out
    movs r2, #0
    str r2, [r3]
    ldr r3, =0x28e24971
    blx r3
    movs r8, #0
wipe_all:
    mov r0, r8
    bl edge
    mov r1, r0
    mov r0, r8
    bl wipe
    add r8, r8, #1
    cmp r8, #ROWS
    bne wipe_all
    b browser_unlock
models:
    adr.w r3, drawn
    movs r2, #1
    str r2, [r3]
    mov r0, sp
    ldr r3, =0x28df0281             @ the level that picks the list, as the stock fill reads it; takes and releases the DSP model lock
    blx r3
    ldrb r0, [sp]
    add r6, r5, r0
    ldrb.w r0, [r6, #0x56e]         @ the category
    ldrb.w r1, [r6, #0x570]         @ the subcategory
    ldr r3, =0x28e0edcd             @ how many models the list has, negative for none
    blx r3
    mov r7, r0
    ldr r3, =0x28e24971
    blx r3
    movs r8, #0
item:
    mov r0, r8
    bl edge
    mov r1, r0
    mov r0, r8
    bl wipe
    movs r0, #0x24
    mla r0, r8, r0, r5
    addw r0, r0, #0x22c             @ the row's icon, an image widget
    ldrb r1, [r0, #0x1d]
    cbz r1, next_item
    ldrb.w r2, [r5, #0x569]         @ the first row's item
    add r2, r8
    cmp r2, r7
    bge next_item
    ldrb.w r0, [r6, #0x56e]
    ldrb.w r1, [r6, #0x570]
    add r3, sp, #4
    ldr r12, =0x28e01205            @ the item, a block-load descriptor: kind, model, second model
    blx r12
    cmp r0, #0
    blt next_item
    ldr r0, [sp, #4]
    add r1, sp, #4
    ldr r3, =0x28e01d51             @ the cost the firmware checks against the preset limit, the second model's included
    blx r3
    cmp r0, #0
    blt next_item
    mov r0, r8
    bl edge
    mov r2, r0
    ldr r1, [sp, #4]
    adds r1, #50
    movs r3, #100
    udiv r1, r1, r3
    mov r0, r8
    bl label
next_item:
    add r8, r8, #1
    cmp r8, #ROWS
    bne item
browser_unlock:
    ldr r3, =0x28e24ae9
    blx r3
browser_out:
    movs r0, #0
    add sp, #8
    pop {r4-r8, pc}

edge:                               @ r0 a browser row, r5 the browser -> r0 the x just right of its icon, within 0..NAMES_X - 1
    movs r1, #0x24
    mla r0, r0, r1, r5
    addw r0, r0, #0x22c
    ldrb r1, [r0, #0x1c]            @ the anchor: its column picks no, half or whole width left of x
    movs r2, #3
    udiv r3, r1, r2
    mls r1, r3, r2, r1
    ldr r2, [r0, #0x14]
    ldr r0, [r0, #0xc]
    add r0, r2
    mul r1, r1, r2
    sub.w r0, r0, r1, asr #1
    cmp r0, #(NAMES_X - 1)
    it gt
    movgt r0, #(NAMES_X - 1)
    cmp r0, #0
    it lt
    movlt r0, #0
    bx lr

wipe:                               @ r0 a browser row, r1 its icon's right edge, r4 the framebuffer: black from there to the names
    push {lr}
    sub sp, #12                     @ 0 height, 4 colour, 8 anchor
    movs r2, #PITCH
    mul r2, r2, r0
    rsb r2, r2, #(LABEL_TOP - 5 * LABEL_SCALE - 2)
    rsb r3, r1, #NAMES_X
    movs r0, #(5 * LABEL_SCALE + 4)
    str r0, [sp]
    movs r0, #0
    str r0, [sp, #4]
    str r0, [sp, #8]
    mov r0, r4
    ldr.w r12, =0x100017e9
    blx r12
    add sp, #12
    pop {pc}

label:                              @ r0 a browser row, r1 a number 0..999, r2 its icon's right edge, r4 the framebuffer: in white, centred between icon and name
    push {r5, r6, lr}
    sub sp, #12
    mov r5, r0
    add r6, r2, #NAMES_X            @ twice the gap's centre
    mov r0, r1
    mov r1, sp
    bl digits
    mov r1, sp
    subs r1, r0, r1
    adr.w r12, style
    movs r2, #LABEL_SCALE
    str r2, [r12]
    mvn r2, #0xff000000            @ white
    str r2, [r12, #4]
    lsls r2, r1, #3                 @ 8 a digit at scale 2
    subs r2, #LABEL_SCALE
    subs r2, r6, r2
    asrs r2, r2, #1                 @ the left edge
    movs r3, #PITCH
    mul r3, r3, r5
    rsb r3, r3, #LABEL_TOP
    mov r0, sp
    bl put
    add sp, #12
    pop {r5, r6, pc}

total:                              @ r0 the blocks' sum in per cent (-1 for none), r1 DSP Disp (Used/All, Free, Used%), r4 the framebuffer
    push {r3-r7, lr}                @ under the widget lock
    mov r6, r0
    mov r5, r1
    adr.w r7, total_widget
    adr.w r0, total_made
    ldrb r1, [r0]
    cbnz r1, made
    movs r1, #1
    strb r1, [r0]
    mov r0, r7
    adr.w r1, total_node
    ldr r3, =0x28e249d1             @ init(widget, node)
    blx r3
    mov r0, r7
    movw r1, #TOTAL_RIGHT
    movs r2, #TOTAL_TOP
    ldr r3, =0x28e24a69             @ setPos: placed before it has text, so its first erase covers nothing
    blx r3
    mov r0, r7
    movs r1, #8                     @ 3 * row + column: x at the right, y at the top
    ldr r3, =0x28e24ac9             @ setAnchor
    blx r3
    mov r0, r7
    movs r1, #TOTAL_FONT
    ldr r3, =0x28e249e9             @ setFont
    blx r3
    mov r0, r7
    mvn r1, #0xff000000
    ldr r3, =0x28e24a29             @ setColor: white, as the title
    blx r3
made:
    movs r1, #0
    cmp r6, #0
    blt show                        @ no DSP model: hidden
    adr.w r1, total_text
    cmp r5, #2
    bhs percent
    mov r0, r6
    cbz r5, show_used
    rsbs r0, r6, #BUDGET            @ 1: Free
    it lt
    movlt r0, #0
    bl digits
    b shown
show_used:                          @ 0: Used/All
    bl digits
    movs r2, #'/'
    strb r2, [r0], #1
    mov r1, r0
    movs r0, #BUDGET
    bl digits
    b shown
percent:                            @ 2: Used%, of the budget
    movs r0, #200
    mul r0, r6, r0
    adds r0, #BUDGET
    movs r2, #BUDGET * 2
    udiv r0, r0, r2
    bl digits
    movs r2, #'%'
    strb r2, [r0], #1
shown:
    movs r2, #0
    strb r2, [r0]
    mov r0, r7
    adr.w r1, total_text
    movs r2, #8
    ldr r3, =0x28e24bc1             @ setText
    blx r3
    movs r1, #1                     @ showing marks it dirty every paint, so it is redrawn whatever the stock paint drew
show:
    mov r0, r7
    ldr r3, =0x28e24bc9             @ setVisible
    blx r3
    mov r0, r4
    mov r1, r4
    mov r2, r7
    ldr r3, =0x28e24c91             @ erase(fb, fb, widget): black over the last text and the new
    blx r3
    mov r0, r4
    mov r1, r4
    mov r2, r7
    ldr r3, =0x28e24c31             @ draw(fb, fb, widget)
    blx r3
    pop {r3-r7, pc}

cost_of:                            @ r0 a block record's index, r7 the DSP model -> r0 the block's cost (hundredths of a per cent), or -1
    movs r2, #0x54
    mla r0, r0, r2, r7
    ldr r0, [r0, #0x14]             @ the block's handle among the preset's nodes
    cmp r0, #0x4b
    bhi no_cost
    add.w r1, r7, #0x4400           @ the node table, as 0x28e0904c and 0x28dfa864 find it
    ldr r1, [r1]
    add.w r1, r1, r0, lsl #2
    ldr r1, [r1, #0x24]
    cbz r1, no_cost
    ldrb r2, [r1, #5]
    cmp r2, #1
    bne no_cost                     @ kind 1: a block object
    ldr r0, [r1, #0x44]             @ its cost, set at block load and summed into the preset total
    bx lr
no_cost:
    mvn r0, #0
    bx lr

number:                             @ r0 an image widget, r1 a number 0..999, r4 the framebuffer: in black at the block's centre
    push {r5-r11, lr}
    sub sp, #16                     @ 0 digits, 8 block side
    mov r5, r0
    mov r0, r1
    mov r1, sp
    bl digits
    mov r1, sp
    subs r7, r0, r1
    ldr r9, [r5, #0x14]
    ldr r10, [r5, #0x18]
    cmp r10, r9
    ite hi
    movhi r0, r9
    movls r0, r10
    str r0, [sp, #8]                @ the block is the square at the top of its image: move mode lifts it in a 28x40 one
    movs r11, #2
fit:                                @ the icon redraw erases only its own rectangle, so the digits must stay a pixel inside it
    lsls r0, r7, #2
    mul r0, r0, r11
    sub r0, r0, r11                 @ width: 3 columns and a 1-column gap per digit, at the scale
    adds r1, r0, #2
    cmp r1, r9
    bgt smaller
    add r1, r11, r11, lsl #2
    adds r1, #2
    ldr r2, [sp, #8]
    cmp r1, r2
    ble fits
smaller:
    subs r11, #1
    bne fit
    b number_out
fits:
    adr.w r12, style
    str r11, [r12]
    movs r1, #0
    str r1, [r12, #4]               @ black
    mov r6, r0
    ldrb r3, [r5, #0x1c]            @ the widget's anchor 0..8: column picks no, half or whole width left of x, row the same for height below y
    movs r2, #3
    udiv r1, r3, r2
    mls r0, r1, r2, r3
    mul r0, r0, r9
    mul r1, r1, r10
    ldr r2, [r5, #0xc]
    sub.w r2, r2, r0, asr #1
    add.w r2, r2, r9, asr #1        @ centre x
    sub.w r9, r2, r6, asr #1        @ the number's left edge
    ldr r2, [r5, #0x10]
    sub.w r2, r2, r1, asr #1
    add r2, r2, r10                 @ top edge
    ldr r3, [sp, #8]
    sub.w r2, r2, r3, asr #1        @ centre y of the block
    add r3, r11, r11, lsl #2
    adds r3, #1
    add.w r3, r2, r3, lsr #1        @ the number's top edge
    mov r2, r9
    mov r1, r7
    mov r0, sp
    bl put
number_out:
    add sp, #16
    pop {r5-r11, pc}

digits:                             @ r0 a number (999 at most), r1 where its ASCII digits go, most significant first -> r0 past them
    push {r4, lr}
    movw r2, #999
    cmp r0, r2
    it hi
    movhi r0, r2
    movs r3, #1
    cmp r0, #10
    it hs
    movhs r3, #2
    cmp r0, #100
    it hs
    movhs r3, #3
    adds r1, r1, r3
    mov r4, r1
    movs r2, #10
digit:
    udiv r12, r0, r2
    mls r3, r12, r2, r0
    adds r3, #'0'
    strb r3, [r1, #-1]!
    movs r0, r12
    bne digit
    mov r0, r4
    pop {r4, pc}

put:                                @ r0 ASCII digits, r1 how many, r2 left edge, r3 top edge, r4 the framebuffer; scale and colour from style
    push {r5-r11, lr}
    sub sp, #16                     @ 0 fill height (the scale), 4 colour, 8 anchor, 12 top edge
    adr.w r12, style
    ldr r5, [r12]
    str r5, [sp]
    ldr r5, [r12, #4]
    str r5, [sp, #4]
    movs r5, #0
    str r5, [sp, #8]                @ anchor 0: x, y the bottom left corner
    str r3, [sp, #12]
    mov r8, r0
    mov r7, r1
    mov r5, r2
    cmp r7, #0
    beq put_out
glyph:
    ldrb r0, [r8], #1
    subs r0, #'0'
    adr.w r1, font
    ldrh.w r9, [r1, r0, lsl #1]
    ldr r6, [sp, #12]
    ldr r3, [sp]
    subs r6, r6, r3                 @ the top row's bottom edge
    movs r10, #5
row:
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
    bne row
    ldr r3, [sp]
    add.w r5, r5, r3, lsl #2
    subs r7, #1
    bne glyph
put_out:
    add sp, #16
    pop {r5-r11, pc}

CUSTOMOS_SETTING_GET
.ltorg
.balign 4
style:                              @ the scale and colour put draws with
    .word 2, 0
drawn:                              @ nonzero while the browser shows labels
    .word 0
font:                               @ 3x5 glyphs, bit 14 the top left pixel, rows of 3 bits: 0..9
    .hword 0b111101101101111, 0b010110010010111, 0b111001111100111, 0b111001111001111, 0b101101111001001
    .hword 0b111100111001111, 0b111100111101111, 0b111001001001001, 0b111101111101111, 0b111101111001111
.balign 4
total_widget:                       @ the total's text widget
    .space 0x30
total_node:
    .space 0x28
total_text:                         @ 999/75 at most
    .space 8
total_made:
    .byte 0
