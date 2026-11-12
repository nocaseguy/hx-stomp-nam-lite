# HXtra features

Everything HXtra adds to the HX Stomp, where to find it, and every setting. The [setup page](https://wisemandenny.github.io/hxtra/web/) builds all of these into one firmware; with [`build.py`](building.md) you choose them with switches.

| Feature | Where it is on the HX Stomp | Switch |
|---|---|---|
| [Tuner settings](#tuner-settings) | The tuner's own settings, on a third page: open the tuner and page right past Trails, Offsets and String 6 | `HX_TUNER=1` |
| [BPM](#bpm) | Home screen: the tempo at the top left, the beat dot beside the preset number · Global Settings > BPM Display | `HX_BPM=1` |
| [Tap LED color](#tap-led-color) | The TAP footswitch: its ring, and its icon and label on the Home screen · Global Settings > Displays, under Tap Tempo LED | `HX_TAP_COLOR=1` |
| [DSP usage display](#dsp-usage-display) | Edit view and model browser: each block's or model's share, the total at the top right · no settings | `HX_DSP_METER=1` |
| [Breathing line](#breathing-line) | Home screen: the line between the signal flow and the knobs · Global Settings > Breathing Line | `HX_BREATHING_LINE=1` |
| [Real block names](#real-block-names) | Model browser and Edit view: each block's title · no settings | `HX_REAL_NAMES=1` |
| [Long press](#long-press) | FS1–FS5 in Stomp footswitch mode · Global Settings > Footswitches, pages 2 to 5 | `HX_LONG_PRESS=1` |
| [More snapshots](#more-snapshots) | The snapshot footswitches, with Footswitch Mode on Snapshot · no settings | `HX_MORE_SNAPSHOTS=1` |
| [Metronome](#metronome) | Model browser: Looper > Metronome > Metronome · the block's knobs | `HX_CLICK=1` |
| [GR meter](#gr-meter) | Home screen, lit by a compressor · knobs on six compressors | `HX_GR=1` |
| [Boot screen](#boot-screen-hx-stomp-only) | The screen at power-on · set when you build | `--splash`, `--splash-text` |
| [NAM A2 Lite](#nam-a2-lite) | Model browser: Amp > NAM | always on |

Every feature here has run on an HX Stomp from RAM before it was released. The setup page builds them all, but Real block names only when you tick its box. Each is off in a plain `build.py` build until its switch is set (an environment variable, or a `build.py` option), and switches combine:

```sh
HX_TUNER=1 HX_BPM=1 HX_DSP_METER=1 HX_MORE_SNAPSHOTS=1 HX_TAP_COLOR=1 python3 build.py path/to/HX_Stomp_v3.80.0_0x103966115.hxf
```

## Custom settings

The features' settings are in Global Settings, each feature in a section of its own after Displays (turn the knob right past Displays): **BPM Display**, then **Breathing Line**, each with its own icon by the title (see [Icons](icons.md), which also makes an icon library of every stock icon from your firmware file). The section strip at the top has room for the six stock sections only, so none of its icons is lit while you are in a feature's. A build with none of these features has no sections after Displays. Long press's settings are in **Footswitches** instead, after FS5 Function, and Tap LED color's in **Displays**, under Tap Tempo LED.

| Feature | Setting | Values | What it does |
|---|---|---|---|
| BPM | **Font Size** | XL, **L** (default), M, S, Off | The tempo's size. XL is digits only: no ` X` with MIDI clock and nothing with no tempo. Off hides the tempo |
| BPM | **Color** | **White** (default), Gray, Red, Orange, Yellow, Green, Cyan, Blue, Purple, Tempo | The tempo's and the dot's colour. Tempo follows the TAP footswitch's colour (Tap LED Color; stock red in a build without it) |
| BPM | **Dot Position** | **Left** (default), Right, Both, Off | Where the beat dot sits, beside the preset number. Off hides the dot; with Font Size Off too the BPM display is off and the TAP ring blinks as stock |
| Tap LED color | **Tap LED Color** | **Red** (default), DkOrange, LtOrange, Yellow, Green, Teal, Blue, Violet, Pink, White, Rainbow, Random | The TAP footswitch's colour: its ring as it blinks the tempo, and its switch icon and TAP/TUNER label on the Home screen. Rainbow steps the ring round the colour wheel at each beat; Random picks a new colour at each beat. Both keep a white label. In Global Settings > Displays, under Tap Tempo LED. |
| Long press | **FS1 Hold Function** … **FS5 Hold Function** | Off, Tuner, FS4, FS5, FS6 … FS10 (defaults FS6 … FS10) | What holding that footswitch for 1 s does. FS4 and FS5 are external switches. In Global Settings > Footswitches, pages 2 and 3, after FS5 Function. |
| Long press | **FS6 Function** … **FS10 Function** | Tuner, Stomp 6 … 10, Bank Up, Bank Dn, PresetUp, PresetDn, SnpshtUp, SnpshtDn, FS Mode>, <FS Mode, AllBypas, TogglEXP (default Stomp) | What that virtual footswitch does, as FS3 … FS5 Function do for the real ones, with Tuner in place of TAP/Tunr. In Global Settings > Footswitches, pages 4 and 5. |
| Breathing line | **Color** | White, Red, Green, Blue, Fire, Ice, Sunset, Ocean, Aurora, Neon, **Rainbow** (default) | The line's colours. The gradients flow along the line: Fire is red, orange and yellow; Ice blue, cyan and white; Sunset purple, pink and orange; Ocean deep blue, blue and aqua; Aurora green, sky blue and violet; Neon magenta, indigo and cyan; Rainbow every hue. Where the motion dims the line, the colours dim with it. |
| Breathing line | **Type** | Off, Steady, **Breathe** (default), Cylon, Comet, Heart, Sparkle | How it moves. Breathe slowly fades the whole line in and out. Cylon sweeps a wide light from end to end and back, slowing at the ends, with a trail behind it. Comet shoots a light across with a long tail. Heart beats lub-dub from the middle. Sparkle twinkles at random. Steady holds the full colour. Off gives back the stock line. |
| Breathing line | **Speed** | 1 … 10, Tempo (default **4**) | One cycle takes 8 s at 1, 4 s at 4, 0.8 s at 10. Tempo follows the tempo (Global BPM or Preset BPM, as Tempo Select says): a beat a cycle for Heart, two for Breathe, Cylon and Comet, four for Steady, eight for Sparkle; with no tempo it runs at 4. |

Every feature's settings are virtual settings: HXtra serves their IDs itself and keeps their values in spare records of the Global Settings store, which the HX Stomp saves with the rest. `tools/setting_ids.py` assigns each its ID and place. A setting no build has stored yet, or whose stored value is out of range, shows its default. Builds before virtual settings kept these settings on real IDs, so the first virtual build starts them on their defaults.

## Tuner settings

<!-- demo: tuner -->
<img src="https://github.com/user-attachments/assets/7decba81-b026-4fb5-95f9-6c8899b2e47c" width="100%" alt="The tuner: Activate set to Press, so one press opens it, then Lock On and its knobs no longer change">

With `HX_TUNER=1`, the tuner's own settings get a page of their own, third: page right past Trails, Offsets and String 6. The string pages (Strings 5–3, then 2 and 1) follow it: few players use the per-string offsets, so the page comes before them. Its knobs set them as the stock pages' knobs do: turn to change, press to go back to the default.

| Knob | Values | What it does |
|---|---|---|
| **Activate** (Tuner Activation) | **Hold** (default), **Press** | A footswitch assigned TAP/Tunr normally taps the tempo, and holding it opens the tuner. On **Press**, pressing it opens the tuner at once and the tempo is no longer tapped. It follows the assignment, so it works on whichever footswitch has TAP/Tunr. |
| **Lock** (Lock Tuner Settings) | **Off** (default), **On** | On stops the tuner's other settings (Output, Refrnc, Type, Trails, Offsets) from changing: knob turns and the knob presses that reset an item to its default are ignored. Paging still works, and this page's knobs still turn, so Lock can be turned off where it was turned on. |

Both keep their values (setting IDs 29 and 104) from builds that had them in Global Settings > HXtra.

## BPM

<!-- demo: bpm -->
<img src="https://github.com/user-attachments/assets/62783af2-506f-4878-80ed-e2705acba51c" width="49%" alt="Tapping TAP: the tempo and its beat dot follow"> <img src="https://github.com/user-attachments/assets/4579e864-8a7d-46fd-a764-ec5cd102b6e9" width="49%" alt="Global Settings, BPM Display: Font Size, Color and Dot Position">

The Home screen shows the tempo at its top left, and a beat dot beside the preset number that lights with the TAP footswitch's ring, red on a tap.

- **The tempo** is the one the HX Stomp is using, the global or the preset's as Tempo Select says, as a whole number. It shows ` X` after it while the tempo comes from MIDI clock (the tempo screen's Extrnl), and `--` with no tempo.
- **The dot** keeps the beat in every footswitch mode, and with Tap Tempo LED off too: the ring then stays dark while the dot blinks.
- **Settings** (Global Settings > BPM Display): Font Size, Color (the tempo's and the dot's; Tempo takes the TAP footswitch's colour) and Dot Position (left of the preset number, right of it, or both). Off on Font Size hides the tempo and on Dot Position the dot; both Off turns the display off without a rebuild. See [Custom settings](#custom-settings).

## Tap LED color

<!-- demo: tap-color -->
<img src="https://github.com/user-attachments/assets/29f1b0a3-fa13-4d40-bfb0-cb426b15079d" width="100%" alt="Tap LED Color: red, green, blue, then Rainbow walking the colour wheel, and BPM Display Color Tempo following it">

The TAP footswitch's ring blinks red with the tempo, and its icon and label on the Home screen are red. Tap LED Color (Global Settings > Displays, under Tap Tempo LED) picks another colour for all three, from the colours the HX Stomp gives its other footswitches.

- **The colours** are the stock footswitch palette: each ring colour is the one the HX Stomp lights for a block of that colour, and each icon the stock switch icon of that colour.
- **Rainbow** moves the ring a small step round the colour wheel at each beat: 42 shades blended from the palette's Red, DkOrange, Yellow, Green, Blue and Violet, back to Red, about 21 s round at 120 BPM.
- **Random** lights the ring in a random colour of the palette at each beat, never the same twice running.
- With Rainbow and Random, the icon and label stay White, and a tap or a preset change re-lights the ring in its current colour without moving on.
- **External MIDI clock:** the ring keeps the stock colour it blinks with then. **Tap Tempo LED** still decides whether the ring blinks at all.
- **BPM Display's Color Tempo** gives the tempo and the beat dot the TAP footswitch's colour, the ring's current one with Rainbow and Random.

## DSP usage display

<!-- demo: dsp-usage -->
<img src="https://github.com/user-attachments/assets/fb8644f3-b5ab-4803-b3be-fefcfb23c7b3" width="100%" alt="Browsing bass amps: the DSP total previews each model, then the added block shows its share">

In the Edit view, each block in the signal-flow row shows its share of the DSP in per cent, in black on the block. The top right corner shows the blocks' total out of 75, e.g. `47/75`.

In the model browser, each model shows the share it would take, in white between its icon and its name, and the top right corner shows the total as in the Edit view.

75 is what blocks may use: the firmware's preset limit of 90%, less the 15% it always keeps. The numbers are the firmware's own fixed cost of each model, the same ones it uses to decide whether a block fits, not a measured load.

## Real block names

<!-- demo: real-names -->
<img src="https://github.com/user-attachments/assets/607728e6-773b-41ae-9619-5a30ca2f50ad" width="100%" alt="The model browser's Distortion list by real names: Xotic EP Booster, Klon Centaur, Ibanez TS808">

Line 6 names its models after the gear they're based on with a twist (Deez One Mod, US Double Nrm). With Real block names, the model browser and the Edit view title each block by that gear instead: Boss DS-1 Mod, Twin Reverb Nrm. The names come from [helixhelp.com/models](https://helixhelp.com/models)' "based on", at most 16 characters.

- **Off unless you ask:** a checkbox on the setup page, unticked, or `HX_REAL_NAMES=1` for `build.py`.
- **What keeps its name:** Line 6 originals, utility blocks and titles that are already real.
- **Presets** keep the same model IDs, so a preset is the same with or without real names, and opens on stock firmware as usual.

## Breathing line

<!-- demo: breathing-line -->
<img src="https://github.com/user-attachments/assets/d492b0aa-1151-42c6-b84a-27f6fd36e5d8" width="49%" alt="Breathing Line types, colours and speeds on the Home screen, on the unit"> <img src="https://github.com/user-attachments/assets/dd1085e1-c51d-4377-8dee-26b8ce5e1423" width="49%" alt="The same, the screen alone: Steady, Breathe, Cylon, Heart, Sparkle, then Aurora, Ice, Fire and Tempo">

Just for fun: the line across the middle of the Home screen, between the signal flow and the knobs, comes alive in the colours, motion and speed you pick. It starts on Rainbow, breathing once every 4 s.

- **Where it shows:** on the Home screen only. Other screens stay stock, and the line stops animating while you're on them.
- **The selected part of the line** is still thicker, as on the stock line, and **Off** gives the stock line back.
- **Settings** (Global Settings > Breathing Line): Color, Type and Speed. See [Custom settings](#custom-settings).

## Long press

<!-- demo: long-press -->
<img src="https://github.com/user-attachments/assets/50a6ecf0-6d87-4556-8ffd-035e4b40987b" width="49%" alt="Tapping and holding FS2, holding FS1 for the tuner, then the Hold and FS6 to FS10 Function settings"> <img src="https://github.com/user-attachments/assets/f0261c29-ef31-4527-8d96-21ef176b67aa" width="49%" alt="A block's Bypass Assign: MIDI In set to the virtual footswitch FS6, then holding FS2 toggles it">

In Stomp footswitch mode, each of FS1–FS5 can have a Hold action (Global Settings > Footswitches, pages 2 and 3: FS1 Hold Function … FS5 Hold Function), and each virtual footswitch FS6–FS10 a function (pages 4 and 5: FS6 Function … FS10 Function). Holding the switch for 1 s runs it; a tap still toggles the switch's own blocks, on release instead of on press, since the press can't tell yet whether it will become a hold.

- **Tuner** opens the tuner, as holding TAP does.
- **FS4, FS5** press that footswitch, as an external switch would.
- **FS6 … FS10** are virtual footswitches. Each toggles the blocks you assign to it: in a block's Bypass Assign, set MIDI In to FS6 … FS10 (the first five steps up from Off; the knob's label reads FootswIn while it's on one). The assignment is saved in the preset, and parameters assigned to the same footswitch through Controller Assign follow it too. They are MIDI CC 20–24 underneath, which is how HX Edit and other MIDI gear see them.
- **FS6 Function … FS10 Function** give a virtual footswitch the same choices FS3 … FS5 Function give a real one, with **Tuner** (opens the tuner) in place of TAP/Tunr, since a hold has no use for a tap. **Stomp**, the default, toggles its blocks as above. The others do what that function does on a press and release of a real footswitch: **Bank Up/Dn** opens the bank in Preset mode, **PresetUp/Dn** and **SnpshtUp/Dn** step the preset or snapshot, **FS Mode> / <FS Mode** step the footswitch mode, **AllBypas** bypasses everything, and **TogglEXP** switches EXP 1/2 and toggles the virtual footswitch's blocks. Holds act only in Stomp mode, so after a function that leaves it (FS Mode, Bank), come back with a real footswitch or the menu. A MIDI CC 20–24 from outside still toggles the blocks, whatever the function.
- A switch with Hold **Off**, a momentary switch, and the Preset and Snapshot footswitch modes work as stock.

## More snapshots

<!-- demo: snapshots -->
<img src="https://github.com/user-attachments/assets/8ce9d86c-cffb-491e-9c47-0430a02a4af7" width="100%" alt="Snapshots 1 to 3, the lit footswitch again for 4 to 6, and again back to 1 to 3">

With Footswitch Mode on Snapshot, the three footswitches select snapshots 1–3 as usual. Press the lit one again and the same footswitches select snapshots 4–6; press the lit one again to come back.

- **Which bank you're in:** in 4–6, the camera icon at the top right and the footswitch labels show 4, 5 or 6.
- **New snapshots:** the first time you flip to a preset's 4–6, each one starts as a copy of the snapshot you flipped from. Edit them as any snapshot: snapshot-controlled parameters, block bypass, tempo and names are kept per snapshot.
- **Saving:** a save keeps all six with the preset. Saving while in 4–6, you hear the matching snapshot of 1–3 for a moment, as the save writes 1–3 first.
- **Stock firmware and HX Edit:** a preset saved with 4–6 still loads on a stock firmware, as snapshots 1–3, and the stock firmware drops 4–6 if it saves the preset again. HX Edit opens, exports and imports these presets, but its exports (`.hlx`) and backups (`.hxb`) hold snapshots 1–3 only. Snapshots 4–6 live on the HX Stomp.
- **Next and previous:** once a preset has snapshots 4–6 (saved with it, or made by a flip since it loaded), the SnpshtUp and SnpshtDn footswitch functions and MIDI CC 69's next and previous (values 8 and 9) step through all six: next on 3 goes to 4 and next on 6 to 1; previous on 1 goes to 6 and previous on 4 to 3. A preset with only 1–3 wraps within them, as stock.
- **MIDI CC 69:** values 0–2 select snapshots 1–3 and values 3–5 select snapshots 4–6, whichever bank you're in. Selecting 4–6 on a preset that has none yet makes them as a flip does. Sending the lit snapshot's own value does what Reselect Snapshot says, as stock.
- **What else changes:** pressing the lit snapshot footswitch no longer does what Reselect Snapshot says. HX Edit's snapshot buttons work within the bank you're in.

## Metronome

<!-- demo: metronome -->
https://github.com/user-attachments/assets/f25be41c-3ab0-45a1-87fa-99cd50194933

A click track in time with the tempo, as a block: add it from the model browser, Looper > Metronome > Metronome, anywhere in the signal flow. It is a mono effect block, listed under Looper so it's easy to find; it isn't a looper. In the signal flow it is teal, lit when on and dim when off, and its icon is a metronome.

| Knob | Values | What it does |
|---|---|---|
| **Time** | a note value, synced to the tempo (**1/4** by default), as a delay's Time | The beat: 100 ms to 8 s. |
| **Level** | −60 … +6 dB (default **−14**) | The click's volume. |
| **Accent** | **Off** (default), 2 … 12 | Every nth beat is a downbeat, a higher click (2 kHz instead of 1 kHz). |
| **Thru** | Off, **On** (default) | On passes your signal with the click under it; Off gives the click alone. |

- **The beat** starts when the block does, and a new tempo or Time counts from the last beat. Tapping the tempo doesn't yet move the beat onto your taps, and [BPM](#bpm)'s dot blinks with the TAP ring, not with the click.
- **Presets** store the block as model 181, as the earlier builds that listed it under Modulation did, so presets made with them keep it.

## GR meter

<!-- demo: gr-meter -->
https://github.com/user-attachments/assets/50b5cd91-f578-4252-a1df-4b73d8ca1995

A gain-reduction meter on the Home screen, lit by the compressor you turn it on in, so you can see how hard it is working. HX Stomp only.

| Knob | Values | What it does |
|---|---|---|
| **Mtr Thk** | 0 … 20 (default **0**, off) | The meter's thickness in pixels; 0 turns it off. |
| **Mtr Pos** | **Middle** (default), Top, Left, Bottom, Right | Where on the Home screen the meter lights up. Middle takes the place of the line across the middle. |
| **Mtr Dir** | **Normal** (default), Reverse | Normal fills left to right or top to bottom; Reverse the other way. |

- **Which compressors:** Deluxe, LA Studio, Kinky, Ampeg Opto, Rochester and Red Squeeze.
- **With NAM:** in a build with the GR meter, NAM A2 Lite runs up to two blocks instead of three.

## Boot screen (HX Stomp only)

```sh
python3 build.py path/to/HX_Stomp_v3.80.0_0x103966115.hxf --splash my_picture.jpg --splash-text "HXS OS v0.1"
```

- Without `--splash`, the boot picture is the stock one with "HX STOMP" relabelled "HXtra STOMP" (`tools/splash_hxtra.py`). It's made from the firmware's own pixels at build time, so the repo holds no Line 6 artwork.
- `--splash` takes any picture macOS can open (PNG, JPEG, HEIC, ...) at any size. The screen is **320x240**; a 320x240 PNG is used exactly as it is, and anything else is converted to it with macOS's `sips`: scaled to cover the screen and cropped at the centre, or with `--splash-fit fit`, scaled to fit inside it on black. Off macOS, give a 320x240 PNG.
- The loading bar crosses the picture about halfway down, and the text sits on it in the bottom 40 rows, in grey (`0xb1b1b1`), so keep the bottom darkish.
- The boot text reads "v1.0.0", the HXtra version, in place of "Firmware 3.80.0". `--splash-text` replaces it with up to 23 characters: ASCII, and emoji, each of which counts as one, e.g. `--splash-text "HXS OS v0.1 🎸"`.
- Each emoji becomes a colour glyph of the line's font, 18 px tall, level with the capitals. On macOS it's rendered from Apple Color Emoji; `--splash-glyph 🎸=guitar.png` (repeatable) gives your own picture instead, and off macOS it's required. A line with emoji is drawn white, not grey, as the firmware shows a glyph's own colours only on a white line.
- The boot screen is an HXtra feature (`tools/features/splash.py`). The flags set its inputs `HX_SPLASH`, `HX_SPLASH_FIT`, `HX_SPLASH_TEXT` and `HX_SPLASH_GLYPHS`, which work as environment variables too, as the other features' flags do.
- `python3 tools/splash_topo.py out.png [--seed N]` draws a neon contour-map picture to start from; `python3 tools/patch_splash.py export firmware.hxf out.png` saves the picture an image has now.
- The bootloader shows its own copy of the stock picture for a moment at power-on, before the firmware starts; that copy is not changed.

This also changes the image store (part 8 of the 15), and with emoji, the font table (part 7).

## NAM A2 Lite

From upstream [hx-stomp-nam-lite](https://github.com/nocaseguy/hx-stomp-nam-lite), unchanged in this fork: [Neural Amp Modeler](https://www.neuralampmodeler.com) A2 Lite captures running on the HX Stomp's own DSP. The setup page converts your `.nam` files into User IRs the block reads.

- **Where:** Amp > NAM, a block with ten knobs and a tone stack. It sits on Xenomorph Fuzz Mono's preset ID 555 (that stock model is removed), so HX Edit keeps NAM blocks, and presets made with either build open with the other.
- **Older presets:** presets saved with an earlier NAM build (preset IDs 147 and 148) don't open NAM A2 Lite in this one: re-add the block in those presets.
- **Captures:** none are included. You bring your own `.nam` files, and their licences are up to their authors.

Upstream's [CHANGELOG.md](../CHANGELOG.md) has the NAM changes.
