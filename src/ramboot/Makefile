# The RAM loader and its overlay hook (RAM_RUN.md). Needs arm-none-eabi-gcc.
# The built files are kept in tools/ramboot/, so the page and tools/hxf_ram.py
# work without a toolchain; tests/test_ramboot.py checks they match this source.
CROSS   = arm-none-eabi-
ARCH    = -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard
CFLAGS  = $(ARCH) -Os -ffreestanding -Wall -Wextra -I.
LDFLAGS = $(ARCH) -T lpc4350_ram.ld -nostartfiles --specs=nano.specs --specs=nosys.specs -Wl,--gc-sections
OUT     = ../../tools/ramboot
B       = build

all: $(OUT)/firmware-ramboot.dfu $(OUT)/ramboot-hook.bin

$(OUT)/firmware-ramboot.dfu: ramboot.c ramboot.h emmc.h sdram.h usb_mon.h startup.c dfu.c dfu.h lpc4350.h lpc4350_ram.ld mkbootimg.py
	mkdir -p $(B) $(OUT)
	$(CROSS)gcc $(CFLAGS) $(LDFLAGS) startup.c ramboot.c dfu.c -o $(B)/firmware-ramboot.elf
	$(CROSS)objcopy -O binary $(B)/firmware-ramboot.elf $(B)/firmware-ramboot.bin
	python3 mkbootimg.py $(B)/firmware-ramboot.bin $@

$(OUT)/ramboot-hook.bin: ramboot_hook.c ramboot_hook.ld
	mkdir -p $(B) $(OUT)
	$(CROSS)gcc $(ARCH) -Os -ffreestanding -fno-builtin -Wall -Wextra -nostdlib -T ramboot_hook.ld \
	    ramboot_hook.c -o $(B)/ramboot-hook.elf
	$(CROSS)objcopy -O binary $(B)/ramboot-hook.elf $@

clean:
	rm -rf $(B)

.PHONY: all clean
