# Contributing to HXtra

Thanks for helping HXtra grow. Bug reports, feature ideas, research findings and code are all welcome.

## Reporting a bug or asking for a feature

[Open an issue](https://github.com/wisemandenny/hxtra/issues/new). For a bug, say which HXtra release you run (the boot screen shows it), what you did, what you expected and what happened instead. A photo of the screen helps a lot.

## Before you start

- Read [How HXtra works](docs/architecture.md) and the [research index](docs/research/INDEX.md).
- Set up a checkout and a stock firmware file as in [Building HXtra](docs/building.md).

## Rules

Add what you learn to the matching note in [docs/research](docs/research/INDEX.md) (see [conventions.md](docs/research/conventions.md)), with its status (verified on unit, verified offline, or hypothesis) and how you found it. Never paste Line 6 code or data there: describe it and give addresses.

Demo recordings of the HX Stomp's screen are never committed: upload the GIF or MP4 in a GitHub issue or pull request comment and use its `github.com/user-attachments` link at the feature's `<!-- demo: ... -->` slot in the README or docs/features.md.

Try every change from RAM on a unit before relying on it, and say in the commit what was seen on the unit and what was only checked offline.

A new feature is a module in `tools/features/<name>.py` with its M4 code in `src/m4/<name>.s`, a section in [docs/features.md](docs/features.md), a card in the README's feature grid with its icon (`docs/assets/icons/<name>.svg`, drawn in the same plain line style as the others; no emoji), its entry on the setup page (`web/index.html`, in English and every translation: es, pt, fr, de, it, ja, zh, ko, ru), and its own `tests/test_<name>.py`. Add each translated string on its own line, as the test `test_translations_have_one_string_a_line` checks, so PRs that edit different strings don't conflict. The live setup page only changes on a release, so updating `web/` in the feature's PR is safe. The module's `WEB` field says how the page offers it: `True` (the default) builds it into every web build, `'opt-in'` makes it an unticked checkbox (as Real block names is), and `False` keeps it off the page altogether. `tools/features/dsp_meter.py` is the simplest, and `tools/features/bpm.py` uses every kind of hook. Prefix the module's entry points with the feature's name. Claim setting IDs in `tools/setting_ids.py` (a new setting takes a virtual ID and a bit field there, in `VIRTUAL`), test M4 code with `tests/m4emu.py` (`tools/m4asm.py` fails the build on an `adr` whose label is 4096 bytes or more away, which clang would assemble wrong without a warning: `adr` to a near label and `add.w` the rest), and build and read the firmware with `tests/firmware.py` (see [Tests](#tests)). A setting's label takes at most 8 characters before the newline of its `Page\nName` and 9 after it; the HX Stomp shows the part after the newline first.

## Tests

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -m "not firmware"                # HXtra's tests, without a stock file
HX_STOMP_HXF=path/to/HX_Stomp_v3.80.0_0x103966115.hxf .venv/bin/pytest   # and the firmware tests: the full run before a merge
.venv/bin/pytest -m nam                           # upstream's NAM A2 Lite tests (slow: the kernel in the simulator)
```

Upstream's NAM A2 Lite tests (`test_nam_lite`, `test_multi_kernel`, `test_web_parity`, `test_patch_amp`, `test_web_i18n`) carry the `nam` marker and are skipped unless the `-m` expression names `nam` (`tests/conftest.py`). The firmware MD5 test still covers NAM A2 Lite's bytes in every build. GitHub Actions runs `-m "not firmware"` and `-m "nam and not firmware"` on every push and pull request. The firmware tests need your own stock file (`HX_STOMP_HXF`, `HX_STOMP_XL_HXF`, `HX_EFFECTS_HXF`) and are skipped without one. They build the whole `.hxf` and compare its MD5 with the one pinned in `tests/test_firmware.py`, so a changed byte anywhere in the firmware fails until the pin is updated on purpose. `web/firmware-worker.js` carries the same pin.

M4 code (the caves `tools/patch_menu.py` writes, and each feature's `.s` module) is tested by running it in [unicorn](https://www.unicorn-engine.org) as a Cortex-M4, with `tests/m4emu.py`: it assembles a module with the generated `hxtra.inc` and stands in for firmware functions with Python stubs that log their calls. A call fails if it runs code that is neither loaded nor a stub (a missing stub), doesn't return (a loop), or changes SP or r4-r11. Take the `m4emu` fixture rather than importing the module, so a file's other tests still run without unicorn. `tests/test_hxtra_m4.py` is the example. `tests/firmware.py` builds Entry 0 from your stock file with the features a test turns on, and reads its code and branches. `m4emu.assemble()` needs Apple's Command Line Tools clang and skips the test without it, so CI (Ubuntu) skips those.

## Releases

For maintainers.

On a Mac, from a clean checkout of the pushed commit to release (usually `main`):

```sh
python3 tools/release.py path/to/HX_Stomp_v3.80.0_0x103966115.hxf v1.0.0
```

It makes the release's `m4cache.json` (about 15 s), then creates the GitHub release `v1.0.0` of that commit with the file attached (`gh release create`, notes generated from the pull requests). Publishing the release starts `.github/workflows/pages.yml`, which publishes the setup page of that tag with the release's `m4cache.json`. `--dry-run` only makes `build/m4cache.json`. It refuses a tag the boot text doesn't show (`tools/features/splash.py` `TEXT`), a checkout with changes, and a commit that isn't pushed. To publish a release's page again, run the workflow by hand with its tag. The repository's Pages are set to deploy from workflows, and its `github-pages` environment lets `v*` tags deploy as well as `main`.
