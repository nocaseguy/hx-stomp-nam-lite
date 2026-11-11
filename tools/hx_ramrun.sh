#!/bin/sh
# hx_ramrun.sh - start a changed HX Stomp (or XL) 3.80 image from RAM with no button:
# a running stock (or RAM-run) application is asked over USB to reboot into the
# DFU loader (tools/hx_dfu_reboot.py), then the RAM loader goes in and
# tools/hxf_ram.py runs the image. If the unit is already in DFU, the first
# step is skipped. Needs dfu-util and pyusb; the loader is tools/ramboot/ (RAM_RUN.md).
#   tools/hx_ramrun.sh build/HX_Stomp_v3.80.0_HXtra.hxf
#   tools/hx_ramrun.sh build/HX_Stomp_XL_v3.80.0_HXtra.hxf HX_Stomp_XL_v3.80.0_0x103966115.hxf
set -e
cd "$(dirname "$0")/.."
img=${1:?usage: tools/hx_ramrun.sh image.hxf|image.l6ia [stock.hxf]}
stock=${2:-${HX_STOMP_HXF:-HX_Stomp_v3.80.0_0x103966115.hxf}}
if ! dfu-util -l 2>/dev/null | grep -q 1fc9:000c; then
    python3 tools/hx_dfu_reboot.py
fi
dfu-util -d 1fc9:000c -a 0 -D tools/ramboot/firmware-ramboot.dfu || true   # (it reports an I/O error once the loader starts)
for i in 1 2 3 4 5 6 7 8 9 10; do        # until the RAM loader answers
    python3 tools/hxf_ram.py info >/dev/null 2>&1 && break
    sleep 1
done
python3 tools/hxf_ram.py run "$img" --stock "$stock" --no-emmc-check
