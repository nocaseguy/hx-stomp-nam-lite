@ more_snapshots.s - snapshots 4 to 6: pressing the lit snapshot footswitch again flips between bank A (snapshots 1-3) and bank B
@ (4-6). The snapshot manager holds three 0x260-byte records; the other bank waits in snaps_shadow, and a flip swaps the two and
@ recalls the same footswitch's snapshot through the stock select. tools/features/more_snapshots.py places the hooks.
.syntax unified
.thumb
.equ SELECT, 0x28de2f91             @ (manager, index): recalls a snapshot
.equ RECORD_INIT, 0x28de14b5        @ (manager, record, name): a record's defaults; takes the manager's lock itself
.equ LOCK, 0x28e24c01
.equ UNLOCK, 0x28e24bb1
.equ MEMCPY, 0x28e24c79
.equ MEMSET, 0x28e24b79
.equ REC, 0x260                     @ a snapshot record
.equ RECS, 0xc                      @ record 0, in the manager
.equ CUR, 0x743                     @ the current snapshot
.equ PREV, 0x744                    @ the one before it
.equ BUSY, 0x9a9                    @ set while select must not run; select returns 0 then
.equ MANAGER, 0x2812c630
.equ ICON, 0x2812ade8               @ the top view's snapshot icon (image widget): a camera, its number in a circle
.equ LABELS, 0x2812a4bc             @ the Home view's footswitch labels in Snapshot mode: the same cameras, 0x24 bytes apart
.equ WIDGET_LOCK, 0x28e24971
.equ WIDGET_UNLOCK, 0x28e24ae9
.equ REDRAW, 0x28db8509             @ (full, partial): the UI repaints; the layout code ends with (0, 1)
.equ FILL, 0x100017e9               @ (fb, x, y, w, h, colour, anchor)
.equ TEXT, 0x28db7aa5               @ (fb, text, length, x, y, font, colour, anchor, mode): mode 1 draws only the glyphs' pixels
.equ DARK, 0x101010                 @ the digit on a lit camera's white circle; black would be the renderer's transparent

snaps_select:                       @ a footswitch press's call of select (manager, index)
    cmp r1, #2
    bhi snaps_stock
    ldrb.w r2, [r0, #CUR]
    cmp r2, r1
    bne snaps_stock
    ldrb.w r2, [r0, #BUSY]
    cbz r2, snaps_flip
snaps_stock:
    ldr r12, =SELECT
    bx r12

snaps_flip:                         @ the lit one again: the other bank, then select(index) from the record the sound came from
    push {r4-r10, lr}
    mov r4, r0
    mov r5, r1
    adr.w r6, snaps_data
    ldrb r0, [r6, #1]
    cbnz r0, snaps_ready
    adr.w r0, snaps_shadow          @ bank B since the preset loaded: three default records, which select fills from the sound
    movs r1, #0
    movw r2, #3 * REC
    ldr r3, =MEMSET
    blx r3
    movs r7, #0
snaps_init:
    adr.w r1, snaps_shadow
    mov.w r2, #REC
    mla r1, r2, r7, r1
    adr.w r2, snaps_names
    add.w r2, r2, r7, lsl #4
    mov r0, r4
    ldr r3, =RECORD_INIT
    blx r3
    adds r7, #1
    cmp r7, #3
    bne snaps_init
    movs r0, #1
    strb r0, [r6, #1]
snaps_ready:
    add.w r0, r4, #4
    ldr r3, =LOCK
    blx r3
    bl snaps_swap
    cmp r5, #0                      @ j, another index: its record stands in for the old one while select runs
    ite eq
    moveq r7, #1
    movne r7, #0
    mov r0, r7
    bl snaps_record
    mov r9, r0
    adr.w r0, snaps_temp
    mov r1, r9
    bl snaps_copy
    adr.w r1, snaps_shadow          @ the record just swapped out holds the sound being left, with its edits
    mov.w r2, #REC
    mla r1, r2, r5, r1
    mov r0, r9
    bl snaps_copy
    ldrb.w r8, [r4, #PREV]
    strb.w r7, [r4, #CUR]           @ so select sees a change from j: it diffs, or copies into an unused record, from there
    add.w r0, r4, #4
    ldr r3, =UNLOCK
    blx r3
    mov r0, r4
    mov r1, r5
    ldr r3, =SELECT
    blx r3
    mov r10, r0
    add.w r0, r4, #4
    ldr r3, =LOCK
    blx r3
    mov r0, r9
    adr.w r1, snaps_temp
    bl snaps_copy
    strb.w r8, [r4, #PREV]
    ldrb r0, [r6]
    eor r0, r0, #1
    strb r0, [r6]
    cbnz r0, snaps_flipped
    movs r1, #3
    strb r1, [r6, #3]               @ back in bank A: the top icon (bit 0) and the labels (bit 1) drawn again over bank B's numbers
snaps_flipped:
    add.w r0, r4, #4
    ldr r3, =UNLOCK
    blx r3
    movs r0, #0
    movs r1, #1
    ldr r3, =REDRAW
    blx r3
    mov r0, r10
    pop {r4-r10, pc}

snaps_loaded:                       @ before the preset parser fills the records: bank A, and bank B starts again
    adr.w r0, snaps_data
    ldrb r1, [r0]
    add.w r1, r1, r1, lsl #1
    lsls r1, r1, #24                @ bank B was live: the cameras must be drawn again (byte 3)
    str r1, [r0]
    bx lr

snaps_paint:                        @ after the top view's paint (framebuffer, view): bank B's number over its snapshot icon's
    movs r1, #1
    adr.w r2, snaps_top
    b snaps_cameras_paint

snaps_home_paint:                   @ after the Home view's paint (framebuffer, view): over its footswitch labels'
    movs r1, #2
    adr.w r2, snaps_labels

snaps_cameras_paint:                @ r0 the framebuffer, r1 this paint's bit in byte 3, r2 its cameras, a list ending in 0
    push {r4-r8, lr}
    mov r4, r0
    mov r5, r1
    mov r6, r2
    adr.w r7, snaps_data
    ldrb r0, [r7]
    ldrb r1, [r7, #3]
    tst r1, r5
    it eq
    cmpeq r0, #0
    beq snaps_cameras_done
    ldr r3, =WIDGET_LOCK
    blx r3
    movs r8, #0
    ldrb r0, [r7, #3]
    tst r0, r5
    beq snaps_cameras_draw
    bic r0, r0, r5
    strb r0, [r7, #3]
    movs r8, #1
    mov r0, r6
snaps_cameras_dirty:
    ldr r1, [r0], #4
    cbz r1, snaps_cameras_draw
    ldr r1, [r1, #0x20]             @ its node: the paint draws it only while the node's byte 0x24 is set
    movs r2, #1
    strb.w r2, [r1, #0x24]
    b snaps_cameras_dirty
snaps_cameras_draw:
    ldrb r0, [r7]
    cbz r0, snaps_cameras_unlock
snaps_cameras_each:
    ldr r0, [r6], #4
    cbz r0, snaps_cameras_unlock
    bl snaps_camera
    b snaps_cameras_each
snaps_cameras_unlock:
    ldr r3, =WIDGET_UNLOCK
    blx r3
    cmp.w r8, #0
    beq snaps_cameras_done
    movs r0, #0                     @ the stock cameras are drawn on the next paint
    movs r1, #1
    ldr r3, =REDRAW
    blx r3
snaps_cameras_done:
    pop {r4-r8, pc}

snaps_camera:                       @ (camera, r4 the framebuffer): 4..6 over a visible stock camera's 1..3, where its image puts it
    push {r4-r7, lr}
    sub sp, #28                     @ 0..16 the stack arguments, 20 the digit
    mov r5, r0
    ldrb r0, [r5, #0x1d]            @ visible
    cmp r0, #0
    beq snaps_camera_done
    ldr r0, [r5]                    @ its image
    adr.w r1, snaps_images
    movs r6, #0
snaps_camera_find:
    ldrh.w r2, [r1, r6, lsl #1]
    cmp r2, r0
    beq snaps_camera_found
    adds r6, #1
    cmp r6, #9
    bne snaps_camera_find
    b snaps_camera_done
snaps_camera_found:
    movs r1, #3
    udiv r7, r6, r1                 @ its style: 0 white, 1 red, 2 lit
    mls r6, r7, r1, r6
    adds r6, #'4'
    strh r6, [sp, #20]              @ with its NUL: the renderer draws to the NUL, using the length only to spot 0 or 1
    ldrb r0, [r5, #0x1c]            @ the anchor: column (x at the left, centre, right) and row (y at the bottom, middle, top)
    udiv r2, r0, r1
    mls r1, r2, r1, r0
    ldr r3, [r5, #0x14]
    mul r1, r1, r3
    ldr r0, [r5, #0xc]
    sub.w r6, r0, r1, lsr #1        @ the camera's left
    ldr r3, [r5, #0x18]
    mul r2, r2, r3
    ldr r0, [r5, #0x10]
    sub.w r5, r0, r2, lsr #1        @ and bottom; its digit's rows are 6..26, inside the circle at 16..42 across [verified offline]
    movs r0, #22
    str r0, [sp]
    movs r0, #0
    cmp r7, #2
    it eq
    mvneq r0, #0xff000000           @ a lit camera's circle is white
    str r0, [sp, #4]
    movs r0, #0
    str r0, [sp, #8]                @ anchor 0: x, y the bottom left corner
    mov r0, r4
    add.w r1, r6, #22
    add.w r2, r5, #6
    movs r3, #16
    ldr r12, =FILL
    blx r12
    adds r0, r5, #1                 @ hx28_boldFont's digits ink rows 5..25 of the cell
    str r0, [sp]
    movs r0, #2
    str r0, [sp, #4]
    ldr r0, =DARK
    cmp r7, #2
    it ne
    mvnne r0, #0xff000000
    str r0, [sp, #8]
    movs r0, #1                     @ anchor 1: x the centre, y the bottom; mode 1: the glyphs' pixels only
    str r0, [sp, #12]
    str r0, [sp, #16]
    mov r0, r4
    add r1, sp, #20
    movs r2, #1
    add.w r3, r6, #29
    ldr r12, =TEXT
    blx r12
snaps_camera_done:
    add sp, #28
    pop {r4-r7, pc}

snaps_saving:                       @ before a preset serializer: bank A live, as a load takes the blocks' live values for its snapshot
    ldr r0, =MANAGER
    adr.w r1, snaps_data
    ldrb r2, [r1]
    cbz r2, snaps_none
    movs r2, #1
    strb r2, [r1, #2]
    b snaps_flip_now
snaps_none:
    bx lr

snaps_saved:                        @ after it: bank B again
    ldr r0, =MANAGER
    adr.w r1, snaps_data
    ldrb r2, [r1, #2]
    cmp r2, #0
    it eq
    bxeq lr
    movs r2, #0
    strb r2, [r1, #2]

snaps_flip_now:                     @ (manager): a flip on the current snapshot; select allowed for it, as the load path allows its own
    push {r4-r6, lr}
    mov r4, r0
    ldrb.w r6, [r4, #BUSY]
    movs r1, #0
    strb.w r1, [r4, #BUSY]
    ldrb.w r1, [r4, #CUR]
    bl snaps_flip
    strb.w r6, [r4, #BUSY]
    pop {r4-r6, pc}

snaps_swap:                         @ the manager's three records and snaps_shadow trade places (r4 the manager)
    push {r4-r6, lr}
    add.w r4, r4, #RECS
    adr.w r5, snaps_shadow
    movs r6, #3
snaps_swap1:
    adr.w r0, snaps_temp
    mov r1, r4
    bl snaps_copy
    mov r0, r4
    mov r1, r5
    bl snaps_copy
    mov r0, r5
    adr.w r1, snaps_temp
    bl snaps_copy
    add.w r4, r4, #REC
    add.w r5, r5, #REC
    subs r6, #1
    bne snaps_swap1
    pop {r4-r6, pc}

snaps_record:                       @ (index) -> its record in the manager (r4)
    mov.w r1, #REC
    mla r0, r0, r1, r4
    adds r0, #RECS
    bx lr

snaps_copy:                         @ (to, from): a record
    mov.w r2, #REC
    ldr r3, =MEMCPY
    bx r3

.ltorg
.balign 4
snaps_top:
    .word ICON, 0
snaps_labels:
    .word LABELS, LABELS + 0x24, LABELS + 0x48, 0
snaps_images:                       @ the stock cameras by style, then number: Icon_Snapshot1..3, 1Red..3Red, 1Sel..3Sel
    .hword 0x1a0, 0x71, 0x10f, 0x156, 0x105, 0x4f, 0x13, 0x202, 0x12a
.balign 4
snaps_names:                        @ bank B's default names, 16 bytes apart
    .ascii "SNAPSHOT 4"
    .space 6
    .ascii "SNAPSHOT 5"
    .space 6
    .ascii "SNAPSHOT 6"
    .space 6
snaps_data:                         @ 0 bank B live, 1 snaps_shadow holds bank B, 2 flipped to bank A for a save, 3 cameras to redraw
    .word 0
snaps_temp:
    .space REC
snaps_shadow:                       @ the bank not live: three records as the manager's
    .space 3 * REC
