@ virtual_settings.s - the Global Settings IDs CustomOS serves itself (tools/setting_ids.py VIRTUAL, 0xcc..0xf9): each value is a bit
@ field of the main-store record of a dead float ID 105..116, which the stock Globals file saves with the other 136 records.
@ tools/patch_menu.py owns GET_VALUE, the limits getter, the class function and the long-label function for virt_get, virt_limits,
@ virt_class and virt_label, and its CustomOS turn and click caves enter virt_turn and virt_click. Features store through virt_set
@ (customos.inc's customos_setting_set), as the stock setter refuses these IDs.
.syntax unified
.thumb
.include "virtual.inc"
.equ RECORDS, 0x2845ee9c            @ main-store records of 40 bytes: type +8, value +0xc
.equ RECORD, 40
.equ STORE_LOCK, 0x2845ee88         @ the settings store's mutex
.equ DIRTY, 0x2845ee95              @ the main store's unsaved flag (0x2845ee90 + 5): the save worker 0x28e1ee68 writes Globals file 1
.equ MUTEX_LOCK, 0x28e24c01
.equ MUTEX_UNLOCK, 0x28e24bb1
.equ MEMCPY, 0x28e24c79             @ (dst, src, n)
.equ SETTINGS_CTX, 0x28e007ed       @ () -> what the stock step takes first
.equ STEP_MATH, 0x28dfe6a9          @ (ctx, limits, cur, delta, out, class, how): 4 encoder counts a step, as every stock knob
.equ CHANGED, 0x28dceb31            @ (view, ID): the Global Settings view repaints the slot showing that ID, as on a stock change
.equ CLASS_ABOVE, 0x28e20255        @ the class function past its `cmp r0,#0xcb; bls`, for IDs above 0xcb
.equ CLASS_BELOW, 0x28e20261        @ its bls target
.equ TURN_STUB, 0x28dcef97          @ the stock turn's generic case: r0 view, r1 slot, r2 table, r3 page; r5 the delta
.equ TURN_EXIT, 0x28dcef8f
.equ CLICK_STUB, 0x28dcee7b         @ the stock click's generic case: the same registers, r4 the view
.equ CLICK_DONE, 0x28dceeab         @ after its reset to default: repaints the page
.equ INT, 2
.equ ENTRY, 8                       @ a table entry: ID (2 bytes), container, first bit, bits, max, default, label index

.thumb_func
virt_get:                           @ GET_VALUE(r0 ID, r1 out): {type, value} at out
    cmp r0, #VIRT_FIRST
    blo 1f
    cmp r0, #VIRT_LAST
    bls 2f
1:  ldr r12, =GET_STOCK
    bx r12
2:  push {r4, lr}
    mov r4, r1
    bl find
    cbz r0, none
    bl value
    movs r1, #INT
    strb r1, [r4]
    str r0, [r4, #4]
    movs r0, #0
    pop {r4, pc}

.thumb_func
virt_limits:                        @ (r0 ID, r1 a 40-byte record): its value, limits and default, as a main-store record
    cmp r0, #VIRT_FIRST
    blo 1f
    cmp r0, #VIRT_LAST
    bls 2f
1:  ldr r12, =LIMITS_STOCK
    bx r12
2:  push {r4, lr}
    mov r4, r1
    bl find
    cbz r0, none
    mov r1, r4
    bl fill
    movs r0, #0
    pop {r4, pc}

none:                               @ an unused virtual ID: what the stock gives every ID it does not know
    mvn r0, #2
    pop {r4, pc}

.thumb_func
virt_class:                         @ (r0 ID, r1 out byte): 0, the main store's class, so the slider reads min and max as fill puts them
    cmp r0, #VIRT_FIRST
    blo 1f
    cmp r0, #VIRT_LAST
    bls 2f
1:  cmp r0, #0xcb
    ite ls
    ldrls r12, =CLASS_BELOW
    ldrhi r12, =CLASS_ABOVE
    bx r12
2:  push {r4, lr}
    mov r4, r1
    bl find
    cmp r0, #0
    beq none
    movs r0, #0
    strb r0, [r4]
    pop {r4, pc}

.thumb_func
virt_label:                         @ (r0 ID, r1 dst, r2 length): the long label
    cmp r0, #VIRT_FIRST
    blo 1f
    cmp r0, #VIRT_LAST
    bls 2f
1:  ldr r12, =LABEL_STOCK
    bx r12
2:  push {r4, r5, r6, lr}
    mov r5, r1
    mov r6, r2
    bl find
    cbz r0, 3f
    ldrb r1, [r0, #7]
    movs r2, #LABEL_LEN
    adr.w r3, labels
    mla r1, r1, r2, r3
    cmp r6, #LABEL_LEN
    it hi
    movhi r6, #LABEL_LEN
    mov r0, r5
    mov r2, r6
    ldr r3, =MEMCPY
    blx r3
    movs r0, #0
    pop {r4, r5, r6, pc}
3:  mvn r0, #2
    pop {r4, r5, r6, pc}

.thumb_func
virt_turn:                          @ the CustomOS turn, from its cave: r0 view, r1 slot, r2 table, r3 page; r5 the delta
    push {r0-r3}
    push {r4, r6, r7, lr}
    sub sp, #64                     @ limits record at sp, current value at sp+40, stepped value at sp+48
    add.w r4, r3, r3, lsl #1
    add r4, r1
    ldrh.w r4, [r2, r4, lsl #1]
    mov r0, r4
    bl find
    movs r6, r0
    beq turn_stock
    mov r1, sp
    bl fill
    movs r0, #INT
    strb r0, [sp, #40]
    ldr r7, [sp, #12]               @ fill's value
    str r7, [sp, #44]
    ldr r3, =SETTINGS_CTX
    blx r3
    sub sp, #16                     @ the step's stack arguments; the buffers above move up by 16
    add r1, sp, #64
    str r1, [sp]                    @ out
    movs r1, #0
    str r1, [sp, #4]                @ class
    movs r1, #1
    str r1, [sp, #8]                @ how: the knob's, with the shared count of encoder steps
    add r1, sp, #16
    add r2, sp, #56
    mov r3, r5
    ldr r12, =STEP_MATH
    blx r12
    add sp, #16
    cmp r0, #0
    blt turn_done
    ldrb r0, [sp, #48]
    cmp r0, #INT
    bne turn_done
    ldr r1, [sp, #52]
    ldrb r0, [r6, #5]
    cmp r1, r0
    it hi
    movhi r1, r0
    cmp r1, r7
    beq turn_done
    mov r0, r6
    bl store
    ldr r0, [sp, #80]               @ the view
    mov r1, r4
    ldr r3, =CHANGED
    blx r3
turn_done:
    add sp, #64
    pop {r4, r6, r7, lr}
    add sp, #16
    ldr r12, =TURN_EXIT
    bx r12
turn_stock:
    add sp, #64
    pop {r4, r6, r7, lr}
    pop {r0-r3}
    ldr r12, =TURN_STUB
    bx r12

.thumb_func
virt_click:                         @ the CustomOS click, from its cave: r0 view, r1 slot, r2 table, r3 page; r4 the view
    push {r0-r3}
    push {r5, r6, r7, lr}
    add.w r5, r3, r3, lsl #1
    add r5, r1
    ldrh.w r0, [r2, r5, lsl #1]
    bl find
    cbz r0, 1f
    ldrb r1, [r0, #6]
    bl store
    pop {r5, r6, r7, lr}
    add sp, #16
    ldr r12, =CLICK_DONE
    bx r12
1:  pop {r5, r6, r7, lr}
    pop {r0-r3}
    ldr r12, =CLICK_STUB
    bx r12

.thumb_func
virt_set:                           @ (r0 ID, r1 value) -> r0 0, or -3 for an ID that is not a virtual setting: customos_setting_set's store
    push {r4, lr}
    mov r4, r1
    bl find
    cbz r0, 1f
    ldrb r1, [r0, #5]
    cmp r4, r1
    it ls
    movls r1, r4                    @ above max: max, where a knob would stop
    bl store
    movs r0, #0
    pop {r4, pc}
1:  mvn r0, #2
    pop {r4, pc}

find:                               @ r0 ID -> r0 its table entry, or 0
    adr.w r1, table
    movs r2, #VIRT_COUNT
1:  ldrh r3, [r1]
    cmp r3, r0
    beq 2f
    adds r1, #ENTRY
    subs r2, #1
    bne 1b
    movs r0, #0
    bx lr
2:  mov r0, r1
    bx lr

record:                             @ r0 entry -> r0 its container's record
    ldrb r0, [r0, #2]
    movs r1, #RECORD
    ldr r2, =RECORDS
    mla r0, r0, r1, r2
    bx lr

mask:                               @ r0 entry -> r0 its field's mask, in place
    ldrb r1, [r0, #4]
    ldrb r2, [r0, #3]
    movs r0, #1
    lsls r0, r1                     @ a shift by 32 gives 0, so a 32-bit field's mask is all ones
    subs r0, #1
    lsls r0, r2
    bx lr

value:                              @ r0 entry -> r0 its value: the default while the container is no int (unset) or the field is above max
    push {r4, r5, r6, lr}
    mov r4, r0
    bl record
    mov r5, r0
    mov r0, r4
    bl mask
    ldrb r1, [r5, #8]
    cmp r1, #INT
    bne 1f
    ldr r1, [r5, #12]
    ands r0, r1
    ldrb r1, [r4, #3]
    lsrs r0, r1
    ldrb r1, [r4, #5]
    cmp r0, r1
    bls 2f
1:  ldrb r0, [r4, #6]
2:  pop {r4, r5, r6, pc}

fill:                               @ r0 entry, r1 a 40-byte record: {0, ID, {int, value}, {int, 0}, {int, max}, {int, default}}
    push {r4, r5, r6, lr}
    mov r4, r0
    mov r5, r1
    bl value
    movs r1, #0
    movs r2, #INT
    str r1, [r5]
    ldrh r3, [r4]
    str r3, [r5, #4]
    strb r2, [r5, #8]
    str r0, [r5, #12]
    strb r2, [r5, #16]
    str r1, [r5, #20]
    strb r2, [r5, #24]
    ldrb r3, [r4, #5]
    str r3, [r5, #28]
    strb r2, [r5, #32]
    ldrb r3, [r4, #6]
    str r3, [r5, #36]
    pop {r4, r5, r6, pc}

store:                              @ r0 entry, r1 value: its field set in the container, an int from then on, and the store unsaved
    push {r4, r5, r6, lr}
    mov r4, r0
    mov r5, r1
    ldr r0, =STORE_LOCK
    ldr r3, =MUTEX_LOCK
    blx r3
    mov r0, r4
    bl record
    mov r6, r0
    ldrb r1, [r6, #8]
    cmp r1, #INT
    beq 1f
    ldrb r0, [r4, #2]
    bl defaults
    b 2f
1:  ldr r0, [r6, #12]
2:  push {r0}
    mov r0, r4
    bl mask
    pop {r1}
    bic.w r1, r1, r0
    ldrb r2, [r4, #3]
    lsl.w r3, r5, r2
    ands r3, r0
    orrs r1, r3
    str r1, [r6, #12]
    movs r1, #INT
    strb r1, [r6, #8]
    ldr r0, =DIRTY
    movs r1, #1
    strb r1, [r0]
    ldr r0, =STORE_LOCK
    ldr r3, =MUTEX_UNLOCK
    blx r3
    pop {r4, r5, r6, pc}

defaults:                           @ r0 container -> r0 every field's default in place: an unset container's starting value
    push {r4, r5}
    adr.w r1, table
    movs r2, #VIRT_COUNT
    movs r3, #0
1:  ldrb r4, [r1, #2]
    cmp r4, r0
    bne 2f
    ldrb r4, [r1, #6]
    ldrb r5, [r1, #3]
    lsls r4, r5
    orrs r3, r4
2:  adds r1, #ENTRY
    subs r2, #1
    bne 1b
    mov r0, r3
    pop {r4, r5}
    bx lr

.ltorg
.p2align 2
table:
    VIRT_TABLE
labels:
    VIRT_LABELS
