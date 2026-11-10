# Gain-reduction meters: standards and best practices

How compressors show their gain reduction (GR): guitar pedals, studio hardware, plugins, metering standards and the DSP literature. Gathered 2026-11-03, as a reference for the HX Stomp GR meter.

Source tags:
- **[M]** a manual or manufacturer page;
- **[S]** a standard;
- **[C]** source code;
- **[R]** a review or retailer page;
- **[F]** a forum;
- **[I]** inference, not confirmed by a source.

## 1. What the meter shows

**Rule: meter the gain the compressor applies, in dB, after its own attack and release smoothing.**
- Leave out makeup gain, Level and Mix.
- Never work GR out from input and output levels.

Every source agrees:

**Pedals.** The meter follows the gain-control circuit.
- Origin Cali76: shows "what the compression circuit is doing" [M].
- Empress Compressor: its meter is driven by the gain reduction control circuit [M].
- MXR M76: the meter "shows gain reduction level and compressor response time" [M].

**Studio hardware.** The meter is driven by the control voltage or the gain element, then calibrated against the measured drop in output.
- 1176: gate control voltage [F].
- LA-2A: a second photocell in the T4 [M/F].
- Distressor: a comparator ladder on the control voltage [M/F].
- Tube-Tech CL 1B: calibrated by injecting a DC voltage into the sidechain [M].

**Plugins.**
- Pro Tools Dyn3: "attenuation applied to the input in dB" [M].
- Ableton: "how much the gain is being reduced at any given moment" [M].
- Waves Renaissance: "instantaneous gain reduction" [M].

**Open-source DSP.** Each one meters the gain computer's output.
- Ardour a-comp: `gainr = Lxg - Lyg` in dB, smoothed [C].
- Calf: `meter_comp = gain` [C].
- LSP: the gain vector `vGain` [C].
- Faust `compressors.lib`: the meter is tapped on the gain signal [C].
- x42 / zita: a min-gain hold [C].

**Why comparing input with output goes wrong [I]:**
- Makeup gain and Mix distort it. At 50% Mix, 10 dB of GR reads as about 4 dB.
- Latency or lookahead puts the two signals out of step.
- The input peak and the output peak in a window fall on different samples.
- Saturation and filters after the gain stage add or remove level.
- At low levels the ratio is noisy.

The method is exact only for a pure gain stage measured sample by sample.

## 2. From audio rate to display rate

- Keep the **largest GR since the last display update**, and reset it when the display reads it.
  - Ardour keeps `max_gainr` per block; zita holds the minimum gain until it is read [C].
- Do **not** show the last value, which aliases.
- Do **not** average, which hides transient GR.
- Display rates are typically 20–60 Hz; JUCE practice is an atomic value polled by a timer [C/F].

## 3. Ballistics on top of the gain

**Rise: instant.**
- The gain already contains the compressor's attack.
- Do **not** apply the compressor's attack or release a second time [I].
- Analog GR needles use VU ballistics, 300 ms to rise and 300 ms to fall [S]. They are widely criticised for missing transients [F].

**Fall: none, or a fixed rate.**
- Pedals: no separate ballistics are documented. MXR says outright that the meter's speed shows the attack and release settings: right to left shows the attack, left to right the release [M].
- Peak meter standards:
  - IEC 60268-10 Type I PPM: 20 dB in 1.7 s, about 12 dB/s [S].
  - Type II PPM: 24 dB in 2.8 s, about 8.6 dB/s [S].
  - IEC TR 60268-18 digital peak meters: the same 20 dB in 1.7 s [S].
- A fall of about 8–12 dB/s keeps short GR readable and avoids flicker at fast Release settings [I].

**Peak hold: optional, about 2–3 s.**
- Pro Tools: 3 s by default [F].
- HoRNet: 3 s [F].
- Sonnox SuprEsser: "the previous couple of seconds" [M].
- FabFilter: hold until clicked [M].
- No guitar pedal manual documents a peak hold.

## 4. Scale

**Ten segments is the most common count**: Origin, Empress, MXR M76 and M87, Darkglass, API 527. Others:
- 5–9 segments on small pedals: Becos, Keeley.
- 16 segments: Boss CP-1X, Distressor.

**The scale is non-linear: fine steps at low GR, the first step at 1–1.5 dB, full scale 20–28 dB.**

| Unit | Steps (dB) | Source |
|---|---|---|
| Origin Cali76 | 1 3 5 8 11 14 17 20 24 28 | [M] |
| API 527 | 1.5 4 6 8 10 12 15 17 19 23 | [M] |
| MXR M76 | labelled 1 3 5 7 10 20 | [M] |
| Empress MKII | 1 … 25 | [R] |
| Keeley Compressor Pro | 1 … 20, 7 segments | [R] |
| Distressor | 1–6 green, 7–10 yellow, 12–26 red, 16 LEDs | [F] |
| Needle meters (1176, API 2500, Neve 33609, SSL) | 0–20 | [M/F] |
| LM3915 driver chip | 3 dB per step, 30 dB | [M]; too coarse for GR [I] |

**Rules [I]:**
- Each segment lights when GR ≥ its step, as a bar.
- Allow 0.2–0.3 dB of hysteresis.
- Spend most segments on 1–8 dB.

**Colour and direction:**
- Colour is either one colour (Empress red, MXR M87 green) or green → yellow → red with depth (Distressor, Becos, Suhr) [M/R].
- MXR fills right to left, like a needle falling from 0 [M].

## 5. Typical guitar GR

| Use | GR | Source |
|---|---|---|
| Mild limiting | 1–3 dB | MXR M76 [M] |
| General use | 3–7 dB | MXR M76 / M87 [M]; Keeley 3–9 dB [R] |
| Loudest playing, for "Added Control" | 8 dB | Empress [M] |
| Chicken pickin', hard limiting | 10 dB | Empress, MXR [M] |
| Nashville squash | 14–20 dB | MXR [M] |

A soft knee starts GR below the nominal threshold. LEDs lighting a little before the threshold is correct behaviour [C/I].

## 6. Line 6's own GR meters

- Helix firmware 2.90 added GR meters to the Compressor and Gate blocks in the inspector, and the 3-Band Comp shows three meters [M].
- These are on Helix Floor, Rack and LT only. **The HX Stomp is not on the list.**
- Scale and ballistics are not documented.
- Users call the 3-Band meter "not very responsive" [F].
- The Helix runs the same DSP models, so its compressor cores may already send a GR value for the inspector [I].

## 7. Recommended practice, summarised

1. Meter the compressor's applied gain in dB, after its smoothing, without makeup, Level or Mix.
2. Between display updates, keep the largest GR, and reset it when the display reads it.
3. Rise instantly. Either show the gain as it is, or let it fall at about 8–12 dB/s. Optionally hold the peak for 2–3 s. Do not apply the compressor's attack or release again.
4. Use a non-linear ten-step scale that starts at 1 dB, with full scale about 20–28 dB and most steps in 1–8 dB.
5. Expect guitar playing to sit around 3–8 dB, with heavy settings at 10–20 dB.

## Sources

- Origin Effects manuals: https://origineffects.com/manuals ; Cali76 Bass guide: https://manuals.plus/m/b28bc47a12e6be6dcbe72c5f524b645b874dcde4efd5460958c2b3bdbe1740fa_optim.pdf
- Empress Compressor: https://empresseffects.com/cdn/shop/files/Compressor_Manual.pdf ; MKII: https://empresseffects.com/cdn/shop/files/Compressor_MKII_manual.pdf
- MXR M76: https://www.jimdunlop.com/content/manuals/M76.pdf ; M87: https://www.jimdunlop.com/content/manuals/M87B.pdf
- Boss CP-1X: https://www.boss.info/us/whats_new/press_releases/2016/BOSS-ANNOUNCES-CP-1X-COMPRESSOR-PEDAL
- Line 6 Helix 2.90: https://helixhelp.netlify.app/release-notes/helix/2-90
- API 527: https://www.manualsdir.com/manuals/754448/api-audio-527-compressor.html?page=6 ; API 2500: https://www.manualslib.com/manual/1446564/Api-2500.html?page=9
- UA 1176: https://help.uaudio.com/hc/en-us/articles/34530260482324-1176-Classic-FET-Compressor-Manual ; LA-2A: https://help.uaudio.com/hc/en-us/articles/19378009641748-LA-2A-Tube-Compressor-Manual
- Neve 33609/N: https://www.ams-neve.com/wp-content/uploads/2022/01/33609N1.0usermanual.pdf
- Tube-Tech CL 1B: https://kmraudio.com/cdn/shop/files/Manual-CL-1B-180515.pdf
- Distressor: https://sonicscoop.com/?p=77717 , https://www.manualsdir.com/manuals/674530/empirical-labs-el-8.html?page=10
- Pro Tools Dyn3: https://apps.avid.com/proToolsFirstHelp/version12.0/enu/Pro%20Tools%20First%20Help/Dyn3.42.05.html
- FabFilter Pro-C 2: https://www.fabfilter.com/help/pro-c/using/displays
- Sonnox SuprEsser: https://www.manualsdir.com/manuals/741877/sonnox-oxford-supresser.html?page=25
- HoRNet: https://hornetplugins.com/real-gr-gain-reduction-meters
- Ardour a-comp: https://github.com/Ardour/ardour/blob/master/libs/plugins/a-comp.lv2/a-comp.c
- Calf: https://github.com/calf-studio-gear/calf/blob/master/src/modules_comp.cpp
- LSP: https://github.com/lsp-plugins/lsp-plugins-compressor/blob/master/src/main/plug/compressor.cpp
- Faust compressors.lib: https://github.com/grame-cncm/faustlibraries/blob/master/compressors.lib
- x42 dpl: https://github.com/x42/dpl.lv2/blob/master/src/peaklim.cc
- Giannoulis, Massberg and Reiss, "Digital Dynamic Range Compressor Design", JAES 60(6), 2012: https://www.aes.org/e-lib/browse.cfm?elib=16354
- VU and PPM: https://en.wikipedia.org/wiki/VU_meter , https://en.wikipedia.org/wiki/Peak_programme_meter
