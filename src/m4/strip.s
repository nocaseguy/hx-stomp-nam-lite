@ strip.s - the icon strip across the top of Global Settings: six slots over STRIP_COUNT categories, a carousel that wraps around.
@ It moves only when the current category is not in it: turning right brings that one in at the last slot, turning left at the first.
@ With 8 categories, turning right from Displays shows 2..7 with 7 lit, then 3..8, then 4..8, 1 with 1 lit, and so round to 1..6.
@ tools/patch_menu.py sends the four stock loops that set the six images here, with the view in r0.
.syntax unified
.thumb
.include "strip.inc"                @ STRIP_COUNT; STRIP_CATS: per category .hword dim, lit, width, 0; STRIP_CENTRES: twice each slot's middle x
.equ SLOTS, 6
.equ CURRENT, 5                     @ the view's current category (byte)
.equ WIDGETS, 0x110                 @ the slots' image widgets in the view, 0x24 bytes each
.equ WIDGET, 0x24
.equ SET_IMAGE, 0x28e24c19          @ (widget, image index)
.equ SET_POS, 0x28e24c69            @ (widget, x, y): the view's constructor anchors them at the left edge and the middle height
.equ Y, 0xa6

.thumb_func
strip_update:                       @ (r0 the view)
    push {r4-r8, lr}
    ldrb r5, [r0, #CURRENT]
    adr.w r3, state
    ldr r6, [r3]                    @ the category in the first slot
    subs r1, r5, r6                 @ how far past it the current one is, around the carousel
    it mi
    addmi r1, #STRIP_COUNT
    cmp r1, #SLOTS
    blo 2f                          @ in the strip: it stays
    ldr r2, [r3, #4]
    subs r2, r5, r2                 @ the step from the category shown last, around the carousel
    it mi
    addmi r2, #STRIP_COUNT
    mov r6, r5                      @ a step left: the current one in the first slot
    lsls r2, r2, #1
    cmp r2, #STRIP_COUNT
    bhi 1f
    subs r6, r5, #SLOTS - 1         @ a step right: in the last slot
    it mi
    addmi r6, #STRIP_COUNT
1:  str r6, [r3]
2:  str r5, [r3, #4]
    add.w r4, r0, #WIDGETS
    movs r7, #0
3:  adr.w r8, cats
    add.w r8, r8, r6, lsl #3        @ the slot's category
    ldrh r1, [r8]
    cmp r6, r5
    it eq
    ldrheq r1, [r8, #2]
    mov r0, r4
    ldr r3, =SET_IMAGE
    blx r3
    adr.w r3, centres
    ldrh.w r1, [r3, r7, lsl #1]
    ldrh r2, [r8, #4]
    subs r1, r1, r2
    asrs r1, r1, #1                 @ the left edge that centres the icon in its slot, as wide as it is
    movs r2, #Y
    mov r0, r4
    ldr r3, =SET_POS
    blx r3
    adds r4, #WIDGET
    adds r6, #1
    cmp r6, #STRIP_COUNT
    it eq
    moveq r6, #0
    adds r7, #1
    cmp r7, #SLOTS
    bne 3b
    pop {r4-r8, pc}

.ltorg
.align 2
cats:
    STRIP_CATS
centres:
    STRIP_CENTRES
.align 2
state:
    .word 0, 0                      @ the category in the first slot, the current one at the last update
