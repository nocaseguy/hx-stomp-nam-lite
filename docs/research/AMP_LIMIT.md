# The HX Stomp's 2-amp limit (measured on the unit, 2026-10-30)

The unit (HX Stomp, NAM A2 Lite firmware: stock 3.80.0 + preset_id 147, dsp_cost 2700) was
driven over USB with `tools/hx_ctl.py set-model`, edit buffer only, nothing saved. Each row
starts from an empty edit buffer (`--clear-after --clear-path-b`); the blocks are added one
by one and read back.

| edit buffer | kinds | Table 1 cost | result |
|---|---|---|---|
| 147 + 147 | 17, 17 | 5,400 | loads |
| 147 + 147 + 147 | 17 ×3 | 8,100 | **dropped**: edit buffer empty |
| 343 ×3 (Bass amp, the cheapest stock amp) | 17 ×3 | 2,325 | **dropped** |
| 147 + 147 + 231 (Mic preamp, Preamp cat 13) | 17 ×3 | 6,243 | **dropped** |
| 147 + 147 + 182 (an effect) | 17, 17, 1 | 5,859 | loads |

So a preset holds at most **2 blocks of kind 17** (Amp and Preamp; the kind is the browser
item's btype, KIT_FX_HOSTS_IMPL 2.1). The DSP budget (9,000 units, 0x28e01e88) is not what
drops these. The earlier "572+41+572 dropped, probably the DSP budget" (HX_USB_CONTROL §6) was
this limit.

Not found in the code yet. The browser's add-block test (0x28dfae0c → cost 0x28e01d50 →
budget 0x28e01e88) has no amp count, and the resource-mask switch before it (0x28dfac98, by
kind 2..30) lets kind 17 through. The count must be elsewhere (preset validation on load is
likely). Untested: kinds 33 (Amp+Cab) and 18 (Preamp+Cab?) against the limit; whether the
browser greys a third amp out or the drop only happens on load.

Consequence: a third NAM block needs a model of another kind (an effect category, kind 1),
not a Preamp copy.
