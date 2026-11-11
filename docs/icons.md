# Icons: the icon library and a feature section's icon

Each feature with settings is a section of its own in Global Settings, after Displays, with a title and an icon next to it, both from the feature; the strip of section icons across the top shows that icon too. The icon is one of the stock firmware's images, picked by name. This page says how to pick one, which images Global Settings itself uses, and how to see all of them. Status tags are as in [FIRMWARE_NOTES.md](../FIRMWARE_NOTES.md).

## See every icon: the icon library

The pictures are Line 6's, so they aren't in this repository. Make the library page from your own stock firmware file:

```sh
python3 tools/icon_library.py HX_Stomp_v3.80.0_0x103966115.hxf      # writes build/icons.html
```

Open `build/icons.html` in a browser. It draws every icon-like image (172 of the image store's 577) at twice its size on a black screen, each with its name, its size and its index, in four groups: the section icons Global Settings shows by the title, the section strip across the top, the section-style pictures Global Settings never draws, and every other `Icon_` image. You can filter the last group by name and show only the icons that fit. The icons HXtra uses are tagged with what uses them, and the names in `ICONS` are tagged **in ICONS**.

## Give a feature's section an icon

1. Pick an image in the library. One that **fits** (no bigger than 30×29, the size of the stock section icons) sits by the title as the stock ones do; a bigger one may run into the title.
2. Put its name in the feature module, next to its `TITLE`:

   ```python
   TITLE = 'BPM Display'
   ICON = 'Icon_Tempo'
   ```

3. If the name isn't in `ICONS` in `tools/patch_menu.py`, add its line there with the index the library shows (`'Icon_Tempo': 0x181,`). The build stops with a message when a feature names an icon that isn't there, and a firmware test checks every line of `ICONS` against the stock image names.

A feature with no `ICON` gets `Icon_Displays`, the stock Displays icon. A section with several pages shows its icon on each of them.

## In use

| Image | Size | Index | Used for |
| --- | --- | --- | --- |
| `Icon_Displays` | 30×21 | 0x48 | the section of a feature with no `ICON` |
| `Icon_Tempo` | 22×29 | 0x181 | BPM Display |
| `Icon_DualIR` | 28×22 | 0x100 | Breathing Line |

## What stock Global Settings shows

**The section icon by the title** [verified on unit]: one per section, from the list at `0x28e3b5b8`. Each feature's section shows its own in the same place.

| Section | Image | Size | Index |
| --- | --- | --- | --- |
| Ins/Outs | `Icon_InsOuts` | 22×23 | 0x1f8 |
| Preferences | `Icon_Prefs` | 24×26 | 0x12b |
| Footswitches | `Icon_Footswitches` | 25×26 | 0x149 |
| EXP Pedals | `Icon_EXPPedals` | 23×26 | 0x14a |
| MIDI/Tempo | `Icon_MIDITempo` | 22×24 | 0x14d |
| Displays | `Icon_Displays` | 30×21 | 0x48 |

**The section strip across the top** [verified offline]: `0x28dcf4d8` draws `Global_<section>` for each section and `Global_<section>Sel` (lit) for the current one, from the lists at `0x28e3b5f8` and `0x28e3b628`. It has six places. In a build with feature sections it is a carousel over all of them (`src/m4/strip.s`), the build's number of sections going round: it moves only to keep the current section in it, lit, bringing it in at the last place on a turn right and the first on a turn left, so past the last section it goes on with Ins/Outs. A feature's strip icon is its `ICON` as the stock ones are to theirs: its black border trimmed, 1.6 times the size, made into a lit picture (brightest at white) and a dim one (0.39 of that), both new images.

| Section | Image | Lit image | Size |
| --- | --- | --- | --- |
| Ins/Outs | `Global_InsOuts` (0x17) | `Global_InsOutsSel` (0x1c7) | 36×36 |
| Preferences | `Global_Prefs` (0x209) | `Global_PrefsSel` (0x3c) | 41×46 |
| Footswitches | `Global_Footswitches` (0x150) | `Global_FootswitchesSel` (0x17c) | 36×38 |
| EXP Pedals | `Global_EXPPedals` (0x11d) | `Global_EXPPedalsSel` (0x5e) | 41×46 |
| MIDI/Tempo | `Global_MIDITempo` (0xfd) | `Global_MIDITempoSel` (0x45) | 36×36 |
| Displays | `Global_Displays` (0xb) | `Global_DisplaysSel` (0x65) | 48×29 |

**Section-style pictures Global Settings never draws** [verified offline]: `Icon_<section>Sel` (0x3e, 0x1de, 0x1c6, 0x19b, 0x1cf, 0x19d, the size of the strip's) and the `Setup_` set: `Setup_Audio`, `Setup_Displays`, `Setup_EXPPedals`, `Setup_Footswitches`, `Setup_MIDI`, `Setup_Prefs`, each with a `Sel` version (36×37 to 62×34). Other screens may use them; that hasn't been checked. All of them are bigger than the section icons.
