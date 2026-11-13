<div align="center">

<a href="https://wisemandenny.github.io/hxtra/web/"><img src="docs/assets/banner.svg" alt="HXtra: custom firmware for the Line 6 HX Stomp" width="100%"></a>

[![Release](https://img.shields.io/github/v/release/wisemandenny/hxtra?style=flat-square&color=ff2e93&label=release)](https://github.com/wisemandenny/hxtra/releases/latest)
[![License: GPL-3.0](https://img.shields.io/github/license/wisemandenny/hxtra?style=flat-square&color=blue)](LICENSE)
[![Stars](https://img.shields.io/github/stars/wisemandenny/hxtra?style=flat-square&color=yellow)](https://github.com/wisemandenny/hxtra/stargazers)
[![Last commit](https://img.shields.io/github/last-commit/wisemandenny/hxtra?style=flat-square)](https://github.com/wisemandenny/hxtra/commits/main)

<!-- demo: tour, a short loop of the virtual HX Stomp from tools/hx_mirror.py -->
<p><img src="https://github.com/user-attachments/assets/b804955a-3275-40b6-932b-d1ccf10c4d95" width="480" alt="A tour of HXtra on the HX Stomp: the BPM and tap colours, DSP usage in the Edit view and model browser, and six snapshots"></p>

</div>

<a href="https://wisemandenny.github.io/hxtra/web/#recovery"><img src="docs/assets/safe.svg" alt="100% safe for your HX Stomp: HXtra never touches the bootloader, so the stock firmware can always go back on." width="100%"></a>

<table>
<tr>
<td width="33%" valign="top">

&nbsp;

<img src="docs/assets/icons/install.svg" width="40" height="40" alt="">

**Nothing to install**

The setup page builds HXtra from your own firmware file, right in your browser. Nothing is uploaded, and there's no software to set up.

&nbsp;

</td>
<td width="33%" valign="top">

&nbsp;

<img src="docs/assets/icons/try.svg" width="40" height="40" alt="">

**Try before you install**

Run HXtra from the HX Stomp's memory for one session. Nothing is written to the unit, and a power-cycle brings back what you had.

&nbsp;

</td>
<td width="33%" valign="top">

&nbsp;

<img src="docs/assets/icons/recover.svg" width="40" height="40" alt="">

**Always recoverable**

If an install ever stops at the splash screen, hold Page Right while powering on and reinstall stock with Line 6 Updater. Every feature ran on a real HX Stomp before release.

&nbsp;

</td>
</tr>
</table>

## Installation

<p align="center"><a href="https://wisemandenny.github.io/hxtra/web/"><img src="docs/assets/install-hxtra.svg" alt="Install HXtra" width="60%"></a></p>

## Features

Every build has all of these + NAM A2 Lite.

<sub>Every demo was recorded from a real HX Stomp's screen, along with its audio and button presses, then overlaid on a simulated HX Stomp.</sub>

### <img src="docs/assets/icons/tuner.svg" width="28" height="28" align="top" alt=""> Tuner settings

*On the tuner's own third page*

- **Tuner button** (Hold, Press): Hold opens the tuner when you hold TAP; Press opens it with a press, and TAP no longer taps the tempo.
- **Tuner lock** (Off, On): On locks the tuner's other settings (Output, Reference, Type, Trails, Offsets).

<!-- demo: tuner -->
<details>
<summary>Demo</summary>

<img src="https://github.com/user-attachments/assets/7decba81-b026-4fb5-95f9-6c8899b2e47c" width="100%" alt="The tuner: Activate set to Press, so one press opens it, then Lock On and its knobs no longer change">

</details>

### <img src="docs/assets/icons/bpm.svg" width="40" height="28" align="top" alt=""> BPM display

*Global Settings › BPM Display*

- **Font size** (XL, L, M, S, Off): the size of the tempo at the top left of the Home screen. Off hides it.
- **Color** (White, Gray, Red, Orange, Yellow, Green, Cyan, Blue, Purple, Tempo): the tempo's and the beat dot's colour. Tempo follows the TAP footswitch's colour (Tap LED Color).
- **Dot position** (Left, Right, Both, Off): where the beat dot blinks with TAP, beside the preset number. Off hides it; with both Off the BPM display is off.

<!-- demo: bpm -->
<details>
<summary>Tap demo</summary>

<img src="https://github.com/user-attachments/assets/62783af2-506f-4878-80ed-e2705acba51c" width="100%" alt="Tapping TAP: the tempo and its beat dot follow">

</details>

<details>
<summary>Settings demo</summary>

<img src="https://github.com/user-attachments/assets/4579e864-8a7d-46fd-a764-ec5cd102b6e9" width="100%" alt="Global Settings, BPM Display: Font Size, Color and Dot Position">

</details>

### <img src="docs/assets/icons/breathing-line.svg" width="28" height="28" align="top" alt=""> Breathing line

*Global Settings › Breathing Line*

- **Color** (White, Red, Green, Blue, Fire, Ice, Sunset, Ocean, Aurora, Neon, Rainbow): the colour or gradient of the line across the middle of the Home screen.
- **Type** (Off, Steady, Breathe, Cylon, Comet, Heart, Sparkle): how it moves; Off gives back the stock line.
- **Speed** (1–10, Tempo): one cycle takes 8 s at 1 and 0.8 s at 10; Tempo follows the tempo, a beat a cycle for Heart, two for Breathe, Cylon and Comet, four for Steady, eight for Sparkle.

<!-- demo: breathing-line -->
<details>
<summary>Unit demo</summary>

<img src="https://github.com/user-attachments/assets/d492b0aa-1151-42c6-b84a-27f6fd36e5d8" width="100%" alt="Breathing Line types, colours and speeds on the Home screen, on the unit">

</details>

<details>
<summary>Screen-only demo</summary>

<img src="https://github.com/user-attachments/assets/dd1085e1-c51d-4377-8dee-26b8ce5e1423" width="100%" alt="The same, the screen alone: Steady, Breathe, Cylon, Heart, Sparkle, then Aurora, Ice, Fire and Tempo">

</details>

### <img src="docs/assets/icons/dsp-usage.svg" width="32" height="32" align="top" alt=""> DSP meter

*No settings*

- Each block shows its share of the DSP, and the top right corner the total, in the Edit view and in the model browser.

<!-- demo: dsp-usage -->
<details>
<summary>Demo</summary>

<img src="https://github.com/user-attachments/assets/fb8644f3-b5ab-4803-b3be-fefcfb23c7b3" width="100%" alt="Browsing bass amps: the DSP total previews each model, then the added block shows its share">

</details>

### <img src="docs/assets/icons/gr-meter.svg" width="28" height="28" align="top" alt=""> Gain reduction meter

*Knobs on the Deluxe, LA Studio, Kinky, Ampeg Opto, Rochester and Red Squeeze compressors*

- **Mtr Thk** (0 … 20): the meter's thickness in pixels; 0, the default, turns it off.
- **Mtr Pos** (Middle, Top, Left, Bottom, Right): where on the Home screen the meter lights up to show how much the compressor is reducing the gain. Middle takes the place of the line across the middle.
- **Mtr Dir** (Normal, Reverse): Normal fills left to right or top to bottom; Reverse the other way.

<!-- demo: gr-meter -->
<details>
<summary>Demo</summary>

https://github.com/user-attachments/assets/50b5cd91-f578-4252-a1df-4b73d8ca1995

</details>

### <img src="docs/assets/icons/long-press.svg" width="28" height="28" align="top" alt=""> Virtual footswitches

*Five extra footswitches, FS6 … FS10, that come with Footswitch long press*

- **Assign a block**: in the block's Bypass Assign, press Page › once to see MIDI In, then turn MIDI In up from Off: FS6 is one click up, FS10 five, and while it's on one of them the knob reads FootswIn. The preset keeps the assignment.
- **Parameters**: assign one to the same FS in Controller Assign, and it follows the footswitch too.
- **MIDI**: **underneath, FS6 … FS10 are MIDI CC 20 … 24.** HX Edit shows them that way, and a MIDI controller sending those CCs switches them as well.

<details>
<summary>Demo</summary>

<img src="https://github.com/user-attachments/assets/f0261c29-ef31-4527-8d96-21ef176b67aa" width="100%" alt="A block's Bypass Assign: MIDI In set to the virtual footswitch FS6, then holding FS2 toggles it">

</details>

### <img src="docs/assets/icons/long-press.svg" width="28" height="28" align="top" alt=""> Footswitch long press

*Global Settings › Footswitches*

- **FS1 … FS5 Hold** (Off, Tuner, FS4, FS5, FS6 … FS10): what holding that footswitch for a second does in Stomp mode. FS6 … FS10 are virtual footswitches: assign blocks to them in Bypass Assign.
- **FS6 … FS10 Function** (Tuner, Stomp, Bank Up, Bank Dn, PresetUp, PresetDn, SnpshtUp, SnpshtDn, FS Mode&gt;, &lt;FS Mode, AllBypas, TogglEXP): what that virtual footswitch does, as FS3 … FS5 Function do for the real ones. Stomp, the default, toggles its blocks.
- **Switch a virtual footswitch**: hold the footswitch whose Hold is set to that FS. By default, holding FS1 switches FS6, and so on up to FS5 and FS10. A tap still toggles the footswitch's own blocks.

<!-- demo: long-press -->
<details>
<summary>Demo</summary>

<img src="https://github.com/user-attachments/assets/50a6ecf0-6d87-4556-8ffd-035e4b40987b" width="100%" alt="Tapping and holding FS2, holding FS1 for the tuner, then the Hold and FS6 to FS10 Function settings">

</details>

### <img src="docs/assets/icons/snapshots.svg" width="104" height="32" align="top" alt=""> More snapshots

*No settings*

- Six snapshots a preset: press the lit snapshot footswitch again to flip between snapshots 1–3 and 4–6.
- Once a preset has snapshots 4–6, next and previous snapshot (SnpshtUp, SnpshtDn, MIDI CC 69) step through all six: next on 3 goes to 4, and next on 6 back to 1.
- MIDI CC 69 selects any of the six directly: values 0–2 for snapshots 1–3, 3–5 for 4–6.

<!-- demo: snapshots -->
<details>
<summary>Demo</summary>

<img src="https://github.com/user-attachments/assets/8ce9d86c-cffb-491e-9c47-0430a02a4af7" width="100%" alt="Snapshots 1 to 3, the lit footswitch again for 4 to 6, and again back to 1 to 3">

</details>

### <img src="docs/assets/icons/tap-color.svg" width="28" height="28" align="top" alt=""> Tap LED color

*Global Settings › Displays*

- **Tap LED Color** (Red, DkOrange, LtOrange, Yellow, Green, Teal, Blue, Violet, Pink, White, Rainbow, Random): the colour of the TAP footswitch's blinking ring, and of its icon and label on the Home screen. Red is the stock colour. Rainbow fades the ring a small step round the colour wheel at each beat, from red through orange, yellow, green, blue, indigo and violet and back; Random picks a new colour at each beat. Both keep the label white.

<!-- demo: tap-color -->
<details>
<summary>Demo</summary>

<img src="https://github.com/user-attachments/assets/29f1b0a3-fa13-4d40-bfb0-cb426b15079d" width="100%" alt="Tap LED Color: red, green, blue, then Rainbow walking the colour wheel, and BPM Display Color Tempo following it">

</details>

### <img src="docs/assets/icons/metronome.svg" width="35" height="28" align="top" alt=""> Metronome

*New block: Looper › Metronome*

- **Time** (a note value, synced to the tempo): the beat, as a delay's Time.
- **Level** (−60 … +6 dB): the click's volume.
- **Accent** (Off, 2 … 12): every nth beat is a downbeat, a higher click.
- **Thru** (Off, On): On plays your signal with the click under it; Off plays the click alone.

<!-- demo: metronome -->
<details>
<summary>Demo</summary>

https://github.com/user-attachments/assets/f25be41c-3ab0-45a1-87fa-99cd50194933

</details>

### <img src="docs/assets/icons/real-names.svg" width="28" height="28" align="top" alt=""> Real block names (optional, off unless you tick it on the setup page)

*No settings*

- Each block's title in the model browser and the Edit view names the gear it's based on: Deez One Mod becomes Boss DS-1 Mod. Line 6 originals keep theirs.

<!-- demo: real-names -->
<details>
<summary>Demo</summary>

<img src="https://github.com/user-attachments/assets/607728e6-773b-41ae-9619-5a30ca2f50ad" width="100%" alt="The model browser's Distortion list by real names: Xotic EP Booster, Klon Centaur, Ibanez TS808">

</details>

### <img src="docs/assets/icons/nam.svg" width="28" height="28" align="top" alt=""> NAM A2 Lite

- [Neural Amp Modeler](https://www.neuralampmodeler.com) captures on the HX Stomp's own DSP, from [hx-stomp-nam-lite](https://github.com/nocaseguy/hx-stomp-nam-lite). The setup page converts your `.nam` files.

### <img src="docs/assets/icons/boot-screen.svg" width="28" height="28" align="top" alt=""> Custom boot screen

- "HXtra STOMP" out of the box, or [your own picture and boot text](docs/features.md#boot-screen-hx-stomp-only), emoji included, from the command-line build.

<div align="center">

<a href="docs/features.md"><img src="docs/assets/feature-guide.svg" alt="Read the feature guide" width="45%"></a>

</div>

## Engineering

<table>
<tr>
<td width="50%" valign="top">

### <img src="docs/assets/icons/dev-pipeline.svg" width="28" height="28" align="top" alt=""> From Python to HX Stomp
A feature is a Python module: it names the stock functions it hooks, declares its settings, and generates any tables its code needs, like Tap LED color's 42 rainbow shades. Its on-device code is Cortex-M4 assembly, which `m4asm` turns into position-independent machine code with `clang`. The engine places that code in free space in the firmware, points each hooked call at it, then rebuilds the `.hxf` and fixes its checksums. The result runs on the HX Stomp from RAM over USB, or installs with Line 6 Updater. The setup page runs the same Python in your browser, with the machine code assembled ahead of time at each release.

&nbsp;

</td>
<td width="50%" valign="top">

### <img src="docs/assets/icons/dev-module.svg" width="28" height="28" align="top" alt=""> One feature, one module
A feature is `tools/features/<name>.py`, plus its Cortex-M4 code in `src/m4/<name>.s`, assembled at build time. It declares its build switch, settings, Global Settings title and icon, and whether the setup page offers it. The build finds every module in the folder: there's no list to register it in.

&nbsp;

</td>
</tr>
<tr>
<td valign="top">

### <img src="docs/assets/icons/dev-hooks.svg" width="28" height="28" align="top" alt=""> Hook layer
Features reach the firmware only through the engine. Several can share one hook (`chain_ptr`, `chain_bl`, `chain_entry`): the Home screen's paint already runs five. A site that can't be shared is claimed by one feature (`own_entry`, `own_call`). Every write checks the stock bytes first, and an overlap fails the build, not the unit.

&nbsp;

</td>
<td valign="top">

### <img src="docs/assets/icons/dev-settings.svg" width="28" height="28" align="top" alt=""> Virtual Global Settings
The HX Stomp saves each Global Setting under a numbered ID, and the stock firmware has only about ten IDs it doesn't use. The first few features used them all up, which would have capped HXtra at a handful of settings. So the engine makes up its own IDs: it answers for them inside the firmware's own settings code, and packs their values into twelve unused setting records that the HX Stomp still saves with everything else. That makes room for 46 settings, 20 used so far. A feature just lists its settings as `Setting(key, label, values, default)`, each feature gets its own section, and the section strip scrolls to fit them all.

&nbsp;

</td>
</tr>
<tr>
<td valign="top">

### <img src="docs/assets/icons/dev-tested.svg" width="28" height="28" align="top" alt=""> Emulated first
Every feature's M4 code runs in an emulator before it runs on a unit: [unicorn](https://www.unicorn-engine.org) as a Cortex-M4 (`tests/m4emu.py`), with Python stubs for the firmware functions it calls. A missing stub, a loop or a clobbered register fails a test, not the HX Stomp. A firmware test pins the MD5 of the whole build, so no byte changes by accident.

&nbsp;

</td>
<td valign="top">

### <img src="docs/assets/icons/dev-mirror.svg" width="28" height="28" align="top" alt=""> Screen mirror and demo videos
A developer build (`HX_SCREEN_MIRROR=1`) streams the HX Stomp's screen over USB, through the channel HX Edit uses, to a window on a Mac at 15 frames a second. `tools/hx_mirror.py` records it with every footswitch, knob and button event, and renders a demo video: the screen set into a photo of the unit (your own copy in `build/art/`, never committed), its controls moving and its footswitch LEDs lighting in time, as an MP4 small enough to attach on GitHub, and a looping GIF of any part of it. Scripts can drive the unit while it records.

&nbsp;

</td>
</tr>
</table>

<div align="center">

<a href="docs/architecture.md"><img src="docs/assets/engineering-guide.svg" alt="Read the engineering guide" width="51%"></a>

</div>

## AI policy

<table>
<tr>
<td width="50%" valign="top">

### <img src="docs/assets/icons/ai-why.svg" width="28" height="28" align="top" alt=""> Why AI
Before a feature can be written, someone has to work out which of thousands of unnamed functions draws the Home screen, how a setting is stored, or what a message between its two processors looks like. Then the change is written as hand-placed machine code that fits into gaps in the existing firmware. This is the kind of tedious, miserable, fragile programming that gives most engineers nightmares. AI made it possible for me to do in one week what would likely have taken me over a year by hand.

&nbsp;

</td>
<td width="50%" valign="top">

### <img src="docs/assets/icons/ai-map.svg" width="28" height="28" align="top" alt=""> 100% reverse engineered
The HX Stomp has no SDK, no documentation, no source code and no debug symbols. Everything HXtra changes had to be found first by reading raw disassembly of a stripped binary that runs on two processors: the Cortex-M4 that runs the screen and footswitches, and the SHARC DSP that processes the audio.

&nbsp;

</td>
</tr>
<tr>
<td valign="top">

### <img src="docs/assets/icons/ai-unit.svg" width="28" height="28" align="top" alt=""> All features verified by hand
I loaded every test build onto my own HX Stomp, played through it, watched the screen and reported back what was actually happening, which is where most bugs were caught. Animation speeds, colours and the click's volume were tuned by eye and ear on the unit, over many rounds.

&nbsp;

</td>
<td valign="top">

### <img src="docs/assets/icons/ai-person.svg" width="28" height="28" align="top" alt=""> Human in charge
The AI did not build this by itself. Working with an AI coding assistant is closer to directing a very fast junior engineer than to pressing a button. It reads disassembly and writes code far faster than I can, but it can be confidently wrong, and it can't touch the pedal, see its screen or hear it. I chose every feature and decided how each should look, feel and behave, and I killed or shelved ideas that turned out to be unsafe or not worth the risk.

&nbsp;

</td>
</tr>
</table>

## FAQ

<table>
<tr>
<td width="50%" valign="top">

### <img src="docs/assets/icons/faq-stock.svg" width="28" height="28" align="top" alt=""> How do I go back to stock firmware?
Install the stock `HX_Stomp_v3.80.0_0x103966115.hxf` with Line 6 Updater, the same way you installed HXtra. If it stops at the splash screen, power it off, **hold Page Right while powering it on** to start it in update mode, and install the stock file from there.

&nbsp;

</td>
<td width="50%" valign="top">

### <img src="docs/assets/icons/faq-presets.svg" width="28" height="28" align="top" alt=""> Will my presets still work?
Presets made on stock firmware open in HXtra. A preset saved with snapshots 4–6 still loads on stock firmware, as snapshots 1–3. HX Edit opens, exports and imports HXtra presets, but its exports (`.hlx`) and backups (`.hxb`) hold snapshots 1–3 only. Presets saved with a NAM build from before HXtra (preset IDs 147 and 148) need their NAM block added again. Back up before you install either way.

&nbsp;

</td>
</tr>
<tr>
<td valign="top">

### <img src="docs/assets/icons/faq-dsp.svg" width="28" height="28" align="top" alt=""> Does HXtra use up my DSP?
Most features run on the HX Stomp's UI processor, not the audio DSP, so they leave your DSP budget alone. The Metronome is a block with a DSP cost of its own, and builds with the gain-reduction meter run NAM A2 Lite on up to two blocks instead of three.

&nbsp;

</td>
<td valign="top">

### <img src="docs/assets/icons/faq-choose.svg" width="28" height="28" align="top" alt=""> Can I choose which features I get?
The setup page builds every feature, plus Real block names if you tick their box. Several can be switched off on the unit: Breathing line Type **Off** gives back the stock line, and the gain-reduction meter stays off until you give it a thickness. To leave a feature out of the firmware altogether, build it with `build.py` and its switches: see [Building HXtra](docs/building.md).

&nbsp;

</td>
</tr>
<tr>
<td valign="top">

### <img src="docs/assets/icons/faq-platforms.svg" width="28" height="28" align="top" alt=""> Which operating systems are supported?
The setup page builds HXtra on Windows, macOS and Linux, in any modern browser; its Run from RAM step needs Chrome or Edge. Installing uses Line 6 Updater, which runs on Windows and macOS. Building from the command line with features needs clang to assemble their code: Apple's Command Line Tools on a Mac, or clang on Linux and WSL (`apt install clang`). Both give the same build, MD5 included.

&nbsp;

</td>
<td valign="top">

### <img src="docs/assets/icons/faq-legal.svg" width="28" height="28" align="top" alt=""> Is this legal?
No Line 6 code or data is in this repository, and no firmware is distributed. You bring your own copy of the official firmware, and the build changes it on your computer. Please don't share the built `.hxf`: it is Line 6's firmware with changes, and it isn't yours or ours to give away. No NAM captures are included either; you bring your own.

&nbsp;

</td>
</tr>
</table>

## Known issues

- With the breathing line on, the BPM beat dot sometimes draws half lit.
- Tapping the tempo doesn't yet move the Metronome's beat onto your taps.

Found something else? [Open an issue](https://github.com/wisemandenny/hxtra/issues/new/choose).

## Acknowledgements

- **[Derek Bui (nocaseguy)](https://github.com/nocaseguy)**, for [hx-stomp-nam-lite](https://github.com/nocaseguy/hx-stomp-nam-lite), the foundation HXtra is forked from. It brought the SHARC assembler and simulator, the NAM A2 Lite kernel, the firmware container tools, the RAM loader and the setup page, and it showed that the HX Stomp's firmware can be changed safely.
- **[Scott (scottlynn73)](https://github.com/scottlynn73)**, for [hx-effects-nam-lite](https://github.com/scottlynn73/hx-effects-nam-lite), the HX Effects port.
- **[ghidra-sharc](https://github.com/roblg/ghidra-sharc)**, whose SHARC opcode tables the assembler adapts.
- **[Neural Amp Modeler](https://github.com/sdatkinson/neural-amp-modeler)**, by Steven Atkinson.
- **[Jason Shimmy](https://jasonshimmy.com/)**, for [HelixHelp](https://helixhelp.com/), whose model list gives Real block names the gear each model is based on.

## License

HXtra is [GPL-3.0-or-later](LICENSE). Third-party notices are in [NOTICE](NOTICE). Line 6, Helix, HX Stomp, HX Effects and HX Edit are trademarks of Yamaha Guitar Group, Inc. HXtra is not affiliated with, endorsed by or supported by Line 6 or Yamaha Guitar Group.
