# Saved A2 Lite presets on an original Helix Floor 3.80

Suddl3 tested one original Floor on November 5, 2026. Two saved single-amp presets recalled different User IR slots after a power cycle and reproduced their earlier USB audio. The two-block listening test and the control freeze below were separate observations. [Public report in issue #8](https://github.com/nocaseguy/hx-stomp-nam-lite/issues/8#issuecomment-6676509410)

## Which build ran

nocaseguy supplied the Stomp A2 Lite implementation, User IR encoding and fixed-input reamp method. The upstream Floor feasibility and cost notes describe stock firmware and a simulated layout. savedadodo ported the kernel, DSP memory layout, controller and firmware packaging to Floor 3.80, and published Floor hardware tests, including split-path overload. The tested port is based on the earlier upstream revision `2e80164`. [Upstream feasibility](HELIX_FLOOR_FEASIBILITY.md) · [Modelled cost](HELIX_FLOOR_KERNEL_COST.md) · [Stomp hardware QA](../../QA.md) · [Pinned Floor source and hardware findings](https://github.com/savedadodo/helix-floor-nam-lite/tree/c7cd0bacaf7e08c0de2b5fedfccb05d13826e9f0/helix-floor)

| Build identifier | Value |
|---|---|
| Source | savedadodo/helix-floor-nam-lite at `c7cd0bacaf7e08c0de2b5fedfccb05d13826e9f0`, `helix-floor/floor/build_floor2.py`, default kernel (NAM2_SHARE) |
| Stock Floor 3.80.0 SHA-256 | `b28f3313064eb7cba2a8fb01d0a34d9358b1a73894591f2aa9d74116e3fbf6dc` |
| Locally built image SHA-256 | `2e6121aceb88519f67911b4fd4c07a34ee80de1b67756311131942c6f5ae9ace` |
| Same image, MD5 in savedadodo’s findings | `95d9e096cbf4f334d8cf7cd0b94e3eb8` |

The local build used the pinned source without tracked edits. All nine build stages passed. Comparing the stock and built archives identified four changed payloads among sixteen entries (0 main application, 2 DSP, 4 model database, 5 graph library). On the PC, the packaged Lite kernel matched 256 reference samples for each of the two amps separately. The simulator supplied the graph caller and modelled DMA.

## What the owner observed

- **Install and recall.** On Windows, Line 6 Updater 1.28 in Offline Mode completed the install after a MODE + TAP startup. An earlier normal-mode attempt showed failure at 0%. HX Edit 3.82 imported model data into User IR slots. The owner saved the NAM presets on the Floor and confirmed normal startup, the recalled model numbers and an audible bypass change.
- **Two blocks in series.** On a straight path, SD-1 Boost (Model 11) fed a Plexi amp + cab (Model 10). With Plexi enabled, toggling the boost audibly changed the sound. The owner heard no crackles while playing and recalled the chain after switching presets and again after a power cycle.
- **Open stability issue.** During one playing incident USB disconnected and the physical controls stopped responding. The owner continued to hear guitar audio. A power cycle restored control. Another control freeze occurred with one NAM block and stock effects. Time to failure, trigger and cause remain unknown. There is no continuous audio recording or DSP timing trace of the incident.

## What the recordings measured

One amp per preset, one straight path, the same four-second input for both amps. Eight accepted seven-second stereo takes cover two models × two bypass states × before/after a normal power cycle. Two preliminary takes with ambiguous bypass state were excluded. All four accepted dry controls correlated above 0.9999999999 with the source. Left and right matched sample for sample throughout each accepted take.

| Recalled User IR | Enabled peak before restart (full scale) | Enabled RMS before restart (aligned 4 s) | Largest absolute sample change after restart (full 7 s, full scale) |
|---|---:|---:|---:|
| 9, D-Lux | 0.13625 | 0.01733 | 0.00000011921 |
| 10, Plexi | 0.28776 | 0.05320 | 0.00000011921 |

Even after fitting the best gain from D-Lux to Plexi, the difference between them was 79.87% of Plexi’s RMS, both before and after restart. The four aligned enabled returns had zero flagged 16-frame repeats or interior digital-silence runs. These short recordings measure two individual amps. The serial boost observation above was by ear.

A separate straight-path recording used D-Lux at Input 5.0 followed by stock Mono Simple Delay (600 ms, feedback 35%, mix 40%, level 0 dB, trails off). At 48 kHz the first echo arrived 28,798 frames after the direct signal (599.96 ms). This run measured one stock effect after NAM.

## Repeat the recall comparison

The [offline checker](../../tools/qa/floor_recall.py) needs Python 3 and NumPy. It generates the original mono stimulus and reads integer PCM WAVs from disk. Recording can use any DAW that can address the Floor’s USB channels.

1. Generate the source with `python tools/qa/floor_recall.py generate di.wav`. Its SHA-256 in this test was `f24ebdd6254a323989289f6ca20b08c7930b0f4242e5f70c102356e20af64ccc`.
2. On a Floor already running the identified port, use two distinct compatible captures of your own in vacant slots. Save a separate straight-path preset for each on the Floor. Write down each model number and keep gains fixed. Slots 9 and 10 identify the original test.
3. For each take, temporarily route USB 3/4 to the top path with output Multi and input gate off. Feed the same DI to the path. Record USB 1/2 as seven seconds of 48 kHz stereo integer PCM (16, 24 or 32 bit). Start the DI one second into the recording and keep the same timing for every take. Select the NAM block itself and check its dim/lit state on the Floor before recording bypass/enabled.
4. Record both states on each preset before power-off. After a normal power cycle, check each recalled Model on the Floor **before** making the temporary USB input edit. Repeat the four takes, then recall the saved guitar preset. Leave the temporary USB edits unsaved.
5. In one folder use the eight filenames formed by `{d-lux,plexi}-{before,after}-{bypass,on}.wav`. The amp prefixes label the two test presets. Run `python tools/qa/floor_recall.py compare di.wav takes` with that folder in place of `takes`.

The checker aligns the left bypass channel to the DI and rejects a dry correlation of 0.98 or less. It aligns the enabled take near the bypass latency, then reports amp-to-amp difference after gain fitting, left/right discrepancy, repeat and silence locations, and file hashes. The restart maximum compares whole takes without alignment, so a shifted recording start affects it. Inspect flagged intervals against the DI, which contains intentional quiet gaps. A different pair of captures will give different levels and waveforms.
