# HXtra

HXtra is a custom firmware for the Line 6 HX Stomp, built by patching the stock 3.80.0 firmware on your own computer.

This repository is a fork of [nocaseguy/hx-stomp-nam-lite](https://github.com/nocaseguy/hx-stomp-nam-lite), which runs **Neural Amp Modeler (NAM) A2 Lite** captures on the HX Stomp. That work is all still here. HXtra takes the same approach further, using the tools that taught the HX Stomp a new amp model to implement new functionality across the rest of the firmware. It grows in small steps, and each one is run on a real HX Stomp from RAM before it is kept.

> **Unofficial and experimental.** Not affiliated with, endorsed by or supported by Line 6 or Yamaha Guitar Group. Installing modified firmware is at your own risk and may void your warranty. Read [Install](#install) and [Recovery](#recovery) before you start.

## Where this came from

[hx-stomp-nam-lite](https://github.com/nocaseguy/hx-stomp-nam-lite), by Derek Bui (nocaseguy), did the hard part: it showed the HX Stomp's firmware can be changed safely. It brought a SHARC assembler and simulator, a NAM A2 Lite kernel written from scratch in SHARC assembly, tools that read and rebuild the `.hxf` container and fix every checksum, a loader that runs a build from RAM without installing it, and an in-browser setup page. It also showed that leaving the bootloader alone keeps a bricked HX Stomp recoverable.

HXtra forks it at upstream commit `2e80164`, has merged upstream up to `01c0bb0`, and builds on those tools. What it adds:

- **New functionality on the Cortex-M4 application** (the HX Stomp's UI and control side), not just the DSP, added as small Thumb-2 code caves that each check the stock bytes they replace.
- **A feature engine.** Each feature is its own module in `tools/features/`, with its own settings, hooks and tests, and features that hook the same place in the firmware share it instead of overwriting each other (see [How it works](#how-it-works)).
- **A way for the DSP to talk to the UI.** A DSP routine writes its own values into the unused tail of the frames the DSP already sends the M4, and an M4 hook reads them. This needs no knowledge of Line 6's own message formats.
- **[FIRMWARE_NOTES.md](FIRMWARE_NOTES.md)**, a shared map of what is known about the 3.80.0 firmware: addresses, formats, techniques that work, dead ends, and what is still open. Every claim is marked verified on the unit, verified offline, or a hypothesis.

The built image is `HX_Stomp_v3.80.0_HXtra.hxf`. NAM A2 Lite is the same block as upstream's: ten knobs and a tone stack in Amp → NAM, on Xenomorph Fuzz Mono's preset ID 555 (that stock model is removed), so HX Edit keeps NAM blocks and presets made with either build open with the other. **Presets saved with an earlier NAM build (preset IDs 147 and 148) don't open NAM A2 Lite in this one:** re-add the block in those presets. Upstream's [CHANGELOG.md](CHANGELOG.md) has the NAM changes.

## Features

Each feature is a module in `tools/features/`; the Metronome's block itself, with its DSP code, is added by `tools/patch_click.py`. They are off by default, and the build adds them when their switch is set (an environment variable, or a `build.py` option). Switches combine. Every feature here has run on an HX Stomp from RAM. The [setup page](#build-in-the-browser) builds all of them.

| Feature | Switch | What it does | Where is it? |
|---|---|---|---|
| **Tuner** | `HX_TUNER=1` | Two more tuner settings: Tuner Activation (open the tuner with a press instead of a hold) and Lock Tuner Settings. See [Tuner settings](#tuner-settings). | The tuner's own settings, on a third page: open the tuner and page right past Trails, Offsets and String 6. |
| **BPM** | `HX_BPM=1` | Shows the tempo, and a beat dot that blinks with the TAP footswitch's ring. See [BPM](#bpm). | Home screen: the tempo at the top left, the dot beside the preset number. Settings: Global Settings > BPM Display. |
| **DSP meter** | `HX_DSP_METER=1` | Shows each block's share of the DSP in per cent and the blocks' total, and in the model browser, the share each model would take. See [DSP meter](#dsp-meter). | Edit view: on each block, the total at the top right. Model browser: between each model's icon and its name, the total at the top right. No settings. |
| **Breathing line** | `HX_BREATHING_LINE=1` | Just for fun: the line comes alive in the colours, motion and speed you pick (Breathe, Cylon, Comet, Heart, Sparkle). See [Breathing line](#breathing-line). | Home screen: the line across the middle, between the signal flow and the knobs. Settings: Global Settings > Breathing Line. |
| **Long press** | `HX_LONG_PRESS=1` | Hold a footswitch for 1 s for a second action: the tuner, FS4 or FS5, or a virtual footswitch FS6–FS10. A tap still toggles the switch's own blocks. See [Long press](#long-press). | FS1–FS5, in Stomp footswitch mode. Settings: Global Settings > Footswitches, pages 2 and 3 (FS1 Hold Function … FS5 Hold Function). |
| **More snapshots** | `HX_MORE_SNAPSHOTS=1` | Six snapshots a preset: press the lit snapshot footswitch again to flip between snapshots 1–3 and 4–6. Snapshots 4–6 are saved with the preset. See [More snapshots](#more-snapshots). | The snapshot footswitches, with Footswitch Mode on Snapshot; in 4–6, the camera icon at the top right and the footswitch labels show the bank. No settings. |
| **Metronome** | `HX_CLICK=1` | A block that plays a click on every beat of the tempo, with an optional accent on the downbeat. HX Stomp only. See [Metronome](#metronome). | Model browser: Looper > Metronome > Metronome. Its settings are the block's knobs: Time, Level, Accent and Thru. |
| **Boot screen** | `--splash`, `--splash-text` | Your own boot picture and boot text, with emoji. Without them, the boot text reads "HXtra". See [Boot screen](#boot-screen-hx-stomp-only). | The screen at power-on, once the firmware starts. Set when you build: no settings on the HX Stomp. |

```sh
HX_TUNER=1 HX_BPM=1 HX_DSP_METER=1 HX_MORE_SNAPSHOTS=1 python3 build.py path/to/HX_Stomp_v3.80.0_0x103966115.hxf
```

### Custom settings

The other features' settings are in Global Settings, each feature in a section of its own after Displays (turn the knob right past Displays): **BPM Display**, then **Breathing Line**, each with its own icon by the title (see [Icons](docs/icons.md), which also makes an icon library of every stock icon from your firmware file). The section strip at the top has room for the six stock sections only, so none of its icons is lit while you are in a feature's. A build with none of these features has no sections after Displays. Long press's settings are in **Footswitches** instead, after FS5 Function.

| Feature | Setting | Values | What it does |
|---|---|---|---|
| BPM | **Font Size** | XL, **L** (default), M, S | The tempo's size. XL is digits only: no ` X` with MIDI clock and nothing with no tempo |
| BPM | **Color** | **White** (default), Gray, Red, Orange, Yellow, Green, Cyan, Blue, Purple | The tempo's and the dot's colour |
| BPM | **Dot Position** | **Left** (default), Right, Both | Where the beat dot sits, beside the preset number |
| Long press | **FS1 Hold Function** … **FS5 Hold Function** | Off, Tuner, FS4, FS5, FS6 … FS10 (defaults FS6 … FS10) | What holding that footswitch for 1 s does. FS4 and FS5 are external switches. In Global Settings > Footswitches, pages 2 and 3, after FS5 Function. |
| Breathing line | **Color** | White, Red, Green, Blue, Fire, Ice, Sunset, Ocean, Aurora, Neon, **Rainbow** (default) | The line's colours. The gradients flow along the line: Fire is red, orange and yellow; Ice blue, cyan and white; Sunset purple, pink and orange; Ocean deep blue, blue and aqua; Aurora green, sky blue and violet; Neon magenta, indigo and cyan; Rainbow every hue. Where the motion dims the line, the colours dim with it. |
| Breathing line | **Type** | Off, Steady, **Breathe** (default), Cylon, Comet, Heart, Sparkle | How it moves. Breathe slowly fades the whole line in and out. Cylon sweeps a wide light from end to end and back, slowing at the ends, with a trail behind it. Comet shoots a light across with a long tail. Heart beats lub-dub from the middle. Sparkle twinkles at random. Steady holds the full colour. Off gives back the stock line. |
| Breathing line | **Speed** | 1 … 10 (default **4**) | One cycle takes 8 s at 1, 4 s at 4, 0.8 s at 10. |

Every feature's settings are virtual settings: HXtra serves their IDs itself and keeps their values in spare records of the Global Settings store, which the HX Stomp saves with the rest. `tools/setting_ids.py` assigns each its ID and place. A setting no build has stored yet, or whose stored value is out of range, shows its default. Builds before virtual settings kept these settings on real IDs, so the first virtual build starts them on their defaults.

### Tuner settings

With `HX_TUNER=1`, the tuner's own settings get a page of their own, third: page right past Trails, Offsets and String 6. The string pages (Strings 5–3, then 2 and 1) follow it: few players use the per-string offsets, so the page comes before them. Its knobs set them as the stock pages' knobs do: turn to change, press to go back to the default.

| Knob | Values | What it does |
|---|---|---|
| **Activate** (Tuner Activation) | **Hold** (default), **Press** | A footswitch assigned TAP/Tunr normally taps the tempo, and holding it opens the tuner. On **Press**, pressing it opens the tuner at once and the tempo is no longer tapped. It follows the assignment, so it works on whichever footswitch has TAP/Tunr. |
| **Lock** (Lock Tuner Settings) | **Off** (default), **On** | On stops the tuner's other settings (Output, Refrnc, Type, Trails, Offsets) from changing: knob turns and the knob presses that reset an item to its default are ignored. Paging still works, and this page's knobs still turn, so Lock can be turned off where it was turned on. |

Both keep their values (setting IDs 29 and 104) from builds that had them in Global Settings > HXtra.

### BPM

The Home screen shows the tempo at its top left, and a beat dot beside the preset number that lights with the TAP footswitch's ring, red on a tap.

- **The tempo** is the one the HX Stomp is using, the global or the preset's as Tempo Select says, as a whole number. It shows ` X` after it while the tempo comes from MIDI clock (the tempo screen's Extrnl), and `--` with no tempo.
- **The dot** keeps the beat in every footswitch mode, and with Tap Tempo LED off too: the ring then stays dark while the dot blinks.
- **Settings** (Global Settings > BPM Display): Font Size, Color (the tempo's and the dot's) and Dot Position (left of the preset number, right of it, or both). See [Custom settings](#custom-settings).

### DSP meter

In the Edit view, each block in the signal-flow row shows its share of the DSP in per cent, in black on the block. The top right corner shows the blocks' total out of 75, e.g. `47/75`.

In the model browser, each model shows the share it would take, in white between its icon and its name, and the top right corner shows the total as in the Edit view.

75 is what blocks may use: the firmware's preset limit of 90%, less the 15% it always keeps. The numbers are the firmware's own fixed cost of each model, the same ones it uses to decide whether a block fits, not a measured load.

### Breathing line

Just for fun: the line across the middle of the Home screen, between the signal flow and the knobs, comes alive in the colours, motion and speed you pick. It starts on Rainbow, breathing once every 4 s.

- **Where it shows:** on the Home screen only. Other screens stay stock, and the line stops animating while you're on them.
- **The selected part of the line** is still thicker, as on the stock line, and **Off** gives the stock line back.
- **Settings** (Global Settings > Breathing Line): Color, Type and Speed. See [Custom settings](#custom-settings).

### Long press

In Stomp footswitch mode, each of FS1–FS5 can have a Hold action (Global Settings > Footswitches, pages 2 and 3: FS1 Hold Function … FS5 Hold Function). Holding the switch for 1 s runs it; a tap still toggles the switch's own blocks, on release instead of on press, since the press can't tell yet whether it will become a hold.

- **Tuner** opens the tuner, as holding TAP does.
- **FS4, FS5** press that footswitch, as an external switch would.
- **FS6 … FS10** are virtual footswitches. Each toggles the blocks you assign to it: in a block's Bypass Assign, set MIDI In to FS6 … FS10 (the first five steps up from Off). The assignment is saved in the preset, and parameters assigned to the same footswitch through Controller Assign follow it too. They are MIDI CC 20–24 underneath, which is how HX Edit and other MIDI gear see them.
- A switch with Hold **Off**, a momentary switch, and the Preset and Snapshot footswitch modes work as stock.

### More snapshots

With Footswitch Mode on Snapshot, the three footswitches select snapshots 1–3 as usual. Press the lit one again and the same footswitches select snapshots 4–6; press the lit one again to come back.

- **Which bank you're in:** in 4–6, the camera icon at the top right and the footswitch labels show 4, 5 or 6.
- **New snapshots:** the first time you flip to a preset's 4–6, each one starts as a copy of the snapshot you flipped from. Edit them as any snapshot: snapshot-controlled parameters, block bypass, tempo and names are kept per snapshot.
- **Saving:** a save keeps all six with the preset. Saving while in 4–6, you hear the matching snapshot of 1–3 for a moment, as the save writes 1–3 first.
- **Stock firmware and HX Edit:** a preset saved with 4–6 still loads on a stock firmware, as snapshots 1–3, and the stock firmware drops 4–6 if it saves the preset again. HX Edit opens, exports and imports these presets, but its exports (`.hlx`) and backups (`.hxb`) hold snapshots 1–3 only. Snapshots 4–6 live on the HX Stomp.
- **What else changes:** pressing the lit snapshot footswitch no longer does what Reselect Snapshot says. Next and previous snapshot, MIDI CC 69 and HX Edit's snapshot buttons work within the bank you're in.

### Metronome

A click track in time with the tempo, as a block: add it from the model browser, Looper > Metronome > Metronome, anywhere in the signal flow. It is a mono effect block, listed under Looper so it's easy to find; it isn't a looper. In the signal flow it is teal, lit when on and dim when off, and its icon is a metronome.

| Knob | Values | What it does |
|---|---|---|
| **Time** | a note value, synced to the tempo (**1/4** by default), as a delay's Time | The beat: 100 ms to 8 s. |
| **Level** | −60 … +6 dB (default **−14**) | The click's volume. |
| **Accent** | **Off** (default), 2 … 12 | Every nth beat is a downbeat, a higher click (2 kHz instead of 1 kHz). |
| **Thru** | Off, **On** (default) | On passes your signal with the click under it; Off gives the click alone. |

- **The beat** starts when the block does, and a new tempo or Time counts from the last beat. Tapping the tempo doesn't yet move the beat onto your taps, and [BPM](#bpm)'s dot blinks with the TAP ring, not with the click.
- **Presets** store the block as model 181, as the earlier builds that listed it under Modulation did, so presets made with them keep it.

### Boot screen (HX Stomp only)

```sh
python3 build.py path/to/HX_Stomp_v3.80.0_0x103966115.hxf --splash my_picture.jpg --splash-text "HXS OS v0.1"
```

- `--splash` takes any picture macOS can open (PNG, JPEG, HEIC, ...) at any size. The screen is **320x240**; a 320x240 PNG is used exactly as it is, and anything else is converted to it with macOS's `sips`: scaled to cover the screen and cropped at the centre, or with `--splash-fit fit`, scaled to fit inside it on black. Off macOS, give a 320x240 PNG.
- The loading bar crosses the picture about halfway down, and the text sits on it in the bottom 40 rows, in grey (`0xb1b1b1`), so keep the bottom darkish.
- The boot text reads "HXtra" in place of "Firmware 3.80.0". `--splash-text` replaces it with up to 23 characters: ASCII, and emoji, each of which counts as one, e.g. `--splash-text "HXS OS v0.1 🎸"`.
- Each emoji becomes a colour glyph of the line's font, 18 px tall, level with the capitals. On macOS it's rendered from Apple Color Emoji; `--splash-glyph 🎸=guitar.png` (repeatable) gives your own picture instead, and off macOS it's required. A line with emoji is drawn white, not grey, as the firmware shows a glyph's own colours only on a white line.
- The boot screen is an HXtra feature (`tools/features/splash.py`). The flags set its inputs `HX_SPLASH`, `HX_SPLASH_FIT`, `HX_SPLASH_TEXT` and `HX_SPLASH_GLYPHS`, which work as environment variables too, as the other features' flags do.
- `python3 tools/splash_topo.py out.png [--seed N]` draws a neon contour-map picture to start from; `python3 tools/patch_splash.py export firmware.hxf out.png` saves the picture an image has now.
- The bootloader shows its own copy of the stock picture for a moment at power-on, before the firmware starts; that copy is not changed.

This also changes the image store (part 8 of the 15), and with emoji, the font table (part 7).

## NAM A2 Lite

From upstream, unchanged in this fork. 

## What this repository contains, and what it doesn't

**No Line 6 code or data is in this repository**, and no firmware file is distributed. You need your own copy of the official firmware file. The build reads it on your computer, applies the changes and writes a new `.hxf` for you. Please don't share the built `.hxf`: it is Line 6's firmware with changes, and it isn't yours or ours to redistribute.

What is here is our own work: the patchers and the offsets they patch, the M4 and SHARC code they add, a SHARC assembler and simulator, the NAM A2 Lite kernel, the RAM loader, and the tools that read the firmware container.

**No NAM captures are included.** You bring your own `.nam` files, and their licences are up to their authors.

## Requirements

- An **HX Stomp**. The **HX Stomp XL** and the **HX Effects** build too, with NAM A2 Lite only, but are **UNTESTED** (see [HX Stomp XL and HX Effects](#hx-stomp-xl-and-hx-effects); on the HX Effects NAM is in Distortion > Mono). Not the Helix Floor, LT or Rack: their firmware is a different design.
- Line 6's firmware 3.80.0 for your unit. The build checks the MD5 and refuses any other file:
  - HX Stomp: `HX_Stomp_v3.80.0_0x103966115.hxf`, MD5 `a2cd8f4ae56f49415380270ebc484bf1`. Download it from [line6.com](https://line6.com/software/readeula.html?rid=12906); you need to sign in with a free Line 6 (Helix) account to get the download.
  - HX Stomp XL: `HX_Stomp_XL_v3.80.0_0x103966115.hxf`, MD5 `329e3a26d60d3de1988b6785fa833ee1`
  - HX Effects: `HX_Effects_v3.80.0_0xd97239907.hxf`, MD5 `7c2ebdf1bffb6bcc5f89dda97f91e40c`
- Python 3.10 or newer with `numpy`: `pip install numpy`. To run a build from RAM from the command line, also `pyusb` and `dfu-util`.
- For every feature but the boot screen, Apple's Command Line Tools (`xcode-select --install`): their M4 code is assembled with its clang at build time. For the boot screen, macOS converts pictures (`sips`) and renders emoji (`swift`); elsewhere give a 320x240 PNG and `--splash-glyph` pictures.
- **Line 6 Updater** to install, and **HX Edit** to import captures.

## Build

```sh
git clone https://github.com/wisemandenny/hxtra.git
cd hxtra
python3 build.py path/to/HX_Stomp_v3.80.0_0x103966115.hxf
```

This writes `build/HX_Stomp_v3.80.0_HXtra.hxf` (from the XL's file, `build/HX_Stomp_XL_v3.80.0_HXtra.hxf`; from the HX Effects', `build/HX_Effects_v3.80.0_HXtra.hxf`). It takes about 2 minutes, most of it the kernel check of step 1. The build:

1. Assembles the NAM kernel and runs it in the SHARC simulator, checking every block's output bit for bit against a reference NAM A2 implementation (`src/sharc/nam_a2.asm`). Add `--no-check` to skip this step.
2. Adds NAM A2 Lite in place of Xenomorph Fuzz Mono (preset ID 555): `tools/patch_amp.py remove-model`, `add-fx-model --knobs eq`, `move-folder` (into Amp > NAM) and `ir-title --knob 6` (the IR name in the block title, from the Model knob). These are `build.py`'s `STEPS`; the HX Effects has its own one step, `effects-eq`.
3. On the HX Stomp, adds the HXtra features that are turned on to the main application (`tools/patch_menu.py`, from `tools/features/`).
4. Adds the kernel to the DSP's boot code (`patch_amp.py patch`).
5. Recomputes and verifies every checksum: the container MD5, the archive Fletcher-32 and CRC-32, and the image CRCs.

The build is deterministic. The default HX Stomp build (no switches) has MD5 `c51c624c93d91f5e510d8f44268e64b4`, pinned in `tests/test_firmware.py`.

A default build changes only 4 of the 15 parts of the firmware: the main application, the DSP program, the model list and the DSP graph library (the boot screen also changes the image store and the font table). **The bootloader is never touched**, which is what keeps [Recovery](#recovery) possible.

## Build in the browser

The setup page, **[wisemandenny.github.io/hxtra](https://wisemandenny.github.io/hxtra/web/)**, does the same build in the browser, with nothing uploaded: you drop your stock `.hxf` and download `HX_Stomp_v3.80.0_HXtra.hxf`, with every feature on, the Metronome block included. It also runs the build from RAM and converts `.nam` captures, and it reads in 10 languages. It runs `build.py`'s own commands in [Pyodide](https://pyodide.org) (`web/firmware-worker.js`); its builds have the same MD5s as `build.py`'s.

The browser has no clang to assemble the features' M4 code, so each release brings that code made in advance: `tools/m4cache.py` runs the page's features on the stock file and keeps what each module assembled to, in `m4cache.json`, with the MD5 of the build, and `tools/m4asm.py` reads it when `HX_M4_CACHE` names it. The page compares its build with that MD5 and says **Verified**. The Metronome block isn't M4 code: the page adds it with `tools/patch_click.py`, as `build.py` does (`m4cache.BUILD_FLAGS`). The GR meter isn't on the page: its DSP side takes NAM A2 Lite's place. A copy of the page served from a checkout (`python3 -m http.server`, then `/web/`) has no `m4cache.json` and builds without features, unless you make one: `python3 tools/m4cache.py path/to/HX_Stomp_v3.80.0_0x103966115.hxf -o m4cache.json`.

The page is published only for a release, never from `main`, so it always matches one; see [Releases](#releases).

## Releases

On a Mac, from a clean checkout of the pushed commit to release (usually `main`):

```sh
python3 tools/release.py path/to/HX_Stomp_v3.80.0_0x103966115.hxf v1.0.0
```

It makes the release's `m4cache.json` (about 15 s), then creates the GitHub release `v1.0.0` of that commit with the file attached (`gh release create`, notes generated from the pull requests). Publishing the release starts `.github/workflows/pages.yml`, which publishes the setup page of that tag with the release's `m4cache.json`. `--dry-run` only makes `build/m4cache.json`. It refuses a tag the boot text doesn't show (`tools/features/splash.py` `TEXT`), a checkout with changes, and a commit that isn't pushed. To publish a release's page again, run the workflow by hand with its tag. The repository's Pages are set to deploy from workflows, and its `github-pages` environment lets `v*` tags deploy as well as `main`.

## Try it first, from RAM

You can run the built firmware from the HX Stomp's memory for one session before you install it. Nothing is written to the HX Stomp, and turning it off and on brings back what is installed. The HX Stomp must have stock 3.80.0 installed. This is how every HXtra change is tested.

Close HX Edit, then:

```sh
python3 tools/hxf_ram.py dfu    # or hold Page Right while you power on
dfu-util -d 1fc9:000c -a 0 -D tools/ramboot/firmware-ramboot.dfu
python3 tools/hxf_ram.py run build/HX_Stomp_v3.80.0_HXtra.hxf --stock HX_Stomp_v3.80.0_0x103966115.hxf
```

The setup page's **Run from RAM** step does the same in Chrome or Edge. Presets and IRs you change during the run are lost at power-off. [RAM_RUN.md](RAM_RUN.md) explains how it works and its limits.

## Install

1. Back up your presets and IRs in HX Edit, then **close HX Edit**.
2. Open Line 6 Updater, choose **Choose File**, and pick `build/HX_Stomp_v3.80.0_HXtra.hxf` (on an XL, the `_XL_` file; never the other unit's).
3. Let it finish and restart the HX Stomp.

## Recovery

If the HX Stomp stops at the splash screen after an install:

1. Power it off. **Hold Page Right while powering it on.** It comes up in update mode, with the screen dark.
2. In Line 6 Updater, choose **Choose File** and pick the stock `HX_Stomp_v3.80.0_0x103966115.hxf`.

This has been done on a real unit after a modified firmware hung at the splash, and it restored stock 3.80.0. It works because the bootloader is left untouched.

## ~HX Stomp XL and HX Effects~

⛔️⛔️ UNTESTED ⛔️⛔️

HXtra has only ever run on an HX Stomp. The XL and HX Effects builds pass the build checks and their pinned MD5s, but no HXtra build has run on either unit, so install one at your own risk and keep the stock file ready for [Recovery](#recovery). Upstream ran earlier NAM A2 Lite builds on both; its notes are in [CHANGELOG.md](CHANGELOG.md). These builds have NAM A2 Lite only, none of the other features, and the HX Effects can't run a build from RAM first: the RAM loader is the HX Stomp's.

## How it works

- **The container.** `tools/hxf.py` and `tools/l6ia.py` read and write the `.hxf` container and the L6IA archive inside it, and `tools/l6ia_verify.py` checks every checksum. There is no encryption or signature.
- **The M4 application.** The HX Stomp's UI runs on an NXP LPC4350 (Cortex-M4). Patches add code caves to the application and reach them with branches from the stock code, and every patch checks the stock bytes before it writes.
- **Features.** `tools/patch_menu.py` is the engine and `tools/features/<name>.py` the features. A feature module declares its switch (`FLAG`, and `INPUTS` for values such as a picture's path), its `SETTINGS`, and `apply(p)` for its code and hooks:
  - **M4 code** is a `src/m4/<name>.s` file, which `p.module()` assembles at build time (`tools/m4asm.py`) with a generated `hxtra.inc` that defines each setting's ID, range and default.
  - **Setting IDs** are claimed in one place, `tools/setting_ids.py`, and the tests fail on a duplicate.
  - **Writes are checked:** every write goes through `Patch.put`, which fails the build if two features write the same bytes.
  - **Shared hooks:** a place several features need is hooked once, with `p.chain_ptr` (a function pointer), `p.chain_bl` (a call) or `p.chain_entry` (a function's start). Its stub runs each feature's handlers around the stock function.
  - **Owned hooks:** a place that can't be shared (stack arguments, or a handler that rewrites them) is taken by one feature with `p.own_entry` (a function's start) or `p.own_call` (a call, such as a tail call).
  - **Other parts:** the image store and fonts (Entries 7 and 8) are changed through `p.entry(n)`, `add_item` and `p.add_glyph` (`tools/image_store.py`), never by hand.
- **The DSP.** The audio runs on an Analog Devices SHARC ADSP-21469. Kernels are hand-written SHARC assembly, assembled by `tools/sharc/sasm.py` and simulated by `tools/sharc/ssim.py`, with no vendor toolchain. A custom kernel is hooked to an unused DSP primitive.
- **NAM captures through the IR slots.** The HX Stomp already stores up to 128 User IRs of 2,048 samples and hands them to the DSP unchanged. `nam2ir.py` packs a capture's weights into those samples, behind a small header the kernel recognises.
- **The NAM block.** `tools/patch_amp.py` builds the block's DSP graph, parameter map and menu entries on Xenomorph Fuzz Mono's identity, with the NAM kernel as its DSP stage (`build.py`'s `STEPS`).

[FIRMWARE_NOTES.md](FIRMWARE_NOTES.md) has the details: addresses, the M4-to-DSP frame format, the Settings and Home screen internals, and the open problems.

## Contributing

Add what you learn to [FIRMWARE_NOTES.md](FIRMWARE_NOTES.md), with its status (verified on unit, verified offline, or hypothesis) and how you found it. Never paste Line 6 code or data there: describe it and give addresses.

Try every change from RAM on a unit before relying on it, and say in the commit what was seen on the unit and what was only checked offline.

A new feature is a module in `tools/features/<name>.py` with its M4 code in `src/m4/<name>.s`, a README section under [Features](#features), and its own `tests/test_<name>.py`. `tools/features/dsp_meter.py` is the simplest, and `tools/features/bpm.py` uses every kind of hook. Prefix the module's entry points with the feature's name. Claim setting IDs in `tools/setting_ids.py` (a new setting takes a virtual ID and a bit field there, in `VIRTUAL`), test M4 code with `tests/m4emu.py`, and build and read the firmware with `tests/firmware.py` (see [Tests](#tests)). A setting's label takes at most 8 characters before the newline of its `Page\nName` and 9 after it; the HX Stomp shows the part after the newline first.

## Tests

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -m "not firmware"                # HXtra's tests, without a stock file
HX_STOMP_HXF=path/to/HX_Stomp_v3.80.0_0x103966115.hxf .venv/bin/pytest   # and the firmware tests: the full run before a merge
.venv/bin/pytest -m nam                           # upstream's NAM A2 Lite tests (slow: the kernel in the simulator)
```

Upstream's NAM A2 Lite tests (`test_nam_lite`, `test_multi_kernel`, `test_web_parity`, `test_patch_amp`, `test_web_i18n`) carry the `nam` marker and are skipped unless the `-m` expression names `nam` (`tests/conftest.py`). The firmware MD5 test still covers NAM A2 Lite's bytes in every build. GitHub Actions runs `-m "not firmware"` and `-m "nam and not firmware"` on every push and pull request. The firmware tests need your own stock file (`HX_STOMP_HXF`, `HX_STOMP_XL_HXF`, `HX_EFFECTS_HXF`) and are skipped without one. They build the whole `.hxf` and compare its MD5 with the one pinned in `tests/test_firmware.py`, so a changed byte anywhere in the firmware fails until the pin is updated on purpose. `web/firmware-worker.js` carries the same pin.

M4 code (the caves `tools/patch_menu.py` writes, and each feature's `.s` module) is tested by running it in [unicorn](https://www.unicorn-engine.org) as a Cortex-M4, with `tests/m4emu.py`: it assembles a module with the generated `hxtra.inc` and stands in for firmware functions with Python stubs that log their calls. A call fails if it runs code that is neither loaded nor a stub (a missing stub), doesn't return (a loop), or changes SP or r4-r11. Take the `m4emu` fixture rather than importing the module, so a file's other tests still run without unicorn. `tests/test_hxtra_m4.py` is the example. `tests/firmware.py` builds Entry 0 from your stock file with the features a test turns on, and reads its code and branches. `m4emu.assemble()` needs Apple's Command Line Tools clang and skips the test without it, so CI (Ubuntu) skips those.

## Layout

```
build.py                      one-step build from the stock .hxf
FIRMWARE_NOTES.md             what is known about the 3.80.0 firmware
tools/patch_menu.py           HXtra: the feature engine, the Global Settings section and its caves (HX Stomp)
tools/features/               the features: tuner.py, bpm.py, breathing_line.py, dsp_meter.py, long_press.py, more_snapshots.py, splash.py
tools/setting_ids.py          which setting ID each feature's setting uses
tools/m4asm.py                assembles a feature's src/m4/*.s with Apple's clang, or takes it from a release's m4cache.json
tools/m4cache.py              a release's m4cache.json: the M4 code of the setup page's features
tools/release.py              makes a release: its m4cache.json on a GitHub release, which publishes the setup page
src/m4/                       the features' M4 code (tuner.s, bpm.s, breathing_line.s, dsp_meter.s, long_press.s, more_snapshots.s)
tools/image_store.py          the image store (Entries 7 and 8): images, fonts, items
tools/icon_library.py         the icon library: every stock icon drawn from your firmware file (docs/icons.md)
tools/patch_splash.py         boot screen pictures; splash_topo.py draws one, splash_emoji.py and emoji_png.swift make emoji glyphs
tools/patch_amp.py            inspect / add-model / ir-title / patch
tools/nam2ir.py               .nam -> User IR .wav
tools/hxf.py, l6ia.py         .hxf container and L6IA archive
tools/l6ia_verify.py          checks every checksum in an archive
tools/hxf_ram.py              runs a build from RAM (RAM_RUN.md); tools/ramboot/ holds the built loader and hook
tools/sharc/nam_multi.py      the NAM kernel's layout, data and simulator check
tools/sharc/nam_multi_kernel.asm
tools/sharc/nam_lite.py       the model format (converter), test model, shared tables, reference run
tools/sharc/nam_pack.py       .nam loader, layer order
tools/sharc/entry4_blob.py    DSP graph library parser
tools/sharc/sasm.py, ssim.py  SHARC assembler and simulator
src/sharc/nam_a2.asm          reference NAM A2 implementation for the check
src/ramboot/                  the RAM loader and its eMMC overlay hook (C, Cortex-M4; make -C src/ramboot)
web/                          the setup page: build, RAM run and converter in the browser (published per release: .github/workflows/pages.yml)
tests/                        pytest: unit, M4 code in unicorn (m4emu.py), web parity, kernel (slow), firmware (firmware.py; needs a stock .hxf)
```

## Licence

GPL-3.0-or-later; see [LICENSE](LICENSE). Third-party notices and trademarks are listed in [NOTICE](NOTICE). NAM A2 Lite and the tools this fork builds on are © Derek Bui ([hx-stomp-nam-lite](https://github.com/nocaseguy/hx-stomp-nam-lite)).
