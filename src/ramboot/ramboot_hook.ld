/* The overlay hook (ramboot_hook.c), linked where hxf_ram.py loads it:
 * RB_HOOK_BASE in ramboot.h. The header comes first; hxf_ram.py puts the
 * overlay table, its sectors and the write pool after _end. */
ENTRY(read_hook)
SECTIONS {
  . = 0x29000000;
  .hdr  : { KEEP(*(.hdr)) }
  .text : { *(.text*) *(.rodata*) }
  .data : { *(.data*) }
  .bss  : { *(.bss*) *(COMMON) }
  /DISCARD/ : { *(.ARM.exidx*) *(.ARM.attributes) *(.comment) }
  . = ALIGN(16);
  _end = .;
}
