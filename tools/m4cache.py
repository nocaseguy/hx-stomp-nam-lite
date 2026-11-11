#!/usr/bin/env python3
"""m4cache.py - the M4 code of the web page's features, made at a release for the page, which has no clang.

usage: m4cache.py <HX_Stomp_v3.80.0_0x103966115.hxf> [-o build/m4cache.json] [--release v1.0.0]

Runs the features of tools/patch_menu.py, all those the page builds, on the image build.py gives them (the stock file with
NAM A2 Lite added: the features' code reads addresses in it), keeping what every module assembled to (keyed by m4asm.key),
then builds the same with build.py to pin its MD5. tools/release.py attaches the file to
the GitHub release, and the Pages workflow publishes it next to the page; m4asm reads it when HX_M4_CACHE names it.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

import features
import m4asm
import patch_amp as pa
import patch_menu as pm

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
UNIT = 'HX_Stomp'                   # the features are the HX Stomp's only


BUILD_FLAGS = ('HX_CLICK',)        # build.py's own switches the page builds too: the Metronome block (tools/patch_click.py)


def web_flags():
    """The switch of each feature the page builds, in feature order (those not marked WEB = False), then BUILD_FLAGS."""
    flags = [features.flags(m)[0] for m in features.load() if features.flags(m) and getattr(m, 'WEB', True)]
    return flags + [f for f in BUILD_FLAGS if f not in flags]


def combo_key(flags):
    return '+'.join(sorted(flags))


def nam_base(stock, d):
    """The image build.py hands tools/patch_menu.py: build.py's STEPS on the stock file, written in the directory d."""
    spec = importlib.util.spec_from_file_location('build', os.path.join(ROOT, 'build.py'))
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    src = stock
    for k, step in enumerate(build.STEPS[UNIT]):
        dst = os.path.join(d, f'nam_lite_{k}.l6ia')
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'patch_amp.py'), step[0], src, dst, *step[1:]],
                           cwd=ROOT, capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f'm4cache: patch_amp.py {step[0]} failed:\n{r.stdout}{r.stderr}')
        src = dst
    return src


def modules(stock, flags):
    """{m4asm.key: {code, symbols}} of every module the features of flags assemble."""
    out, assemble = {}, m4asm.assemble_module

    def keep(src, include=()):
        code, symbols = assemble(src, include)
        out[m4asm.key(src, include)] = {'code': code.hex(), 'symbols': symbols}
        return code, symbols

    with tempfile.TemporaryDirectory() as d:
        data, _ = pa.load_l6ia_from_any(nam_base(stock, d))
    m4asm.assemble_module = keep
    try:
        pm.menu_entries(lambda e: pa.get_entry_swapped(data, e), env={f: '1' for f in flags})
    finally:
        m4asm.assemble_module = assemble
    return out


def built_md5(stock, flags):
    """The MD5 of build.py's .hxf with flags on and no other HX_ variable."""
    env = {k: v for k, v in os.environ.items() if not k.startswith('HX_')}
    env.update({f: '1' for f in flags})
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, 'out.hxf')
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'build.py'), os.path.abspath(stock), '-o', out, '--no-check'],
                           env=env, cwd=ROOT, capture_output=True, text=True)
        if r.returncode or 'ALL OK' not in r.stdout:
            raise SystemExit(f'm4cache: the build with {combo_key(flags) or "no features"} failed:\n{r.stdout}{r.stderr}')
        return hashlib.md5(open(out, 'rb').read()).hexdigest()


def make(stock, release=None):
    if os.environ.get(m4asm.CACHE):
        raise SystemExit(f'm4cache: unset {m4asm.CACHE}: this assembles with clang')
    flags = web_flags()
    return {'release': release, 'unit': UNIT, 'features': flags, 'md5': {UNIT: {combo_key(flags): built_md5(stock, flags)}},
            'modules': modules(stock, flags)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('stock', help='the stock HX Stomp 3.80.0 .hxf')
    ap.add_argument('-o', '--out', default=os.path.join(ROOT, 'build', 'm4cache.json'))
    ap.add_argument('--release', help='the release tag it is made for, shown on the page')
    a = ap.parse_args()
    cache = make(a.stock, a.release)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, 'w') as f:
        json.dump(cache, f, separators=(',', ':'), sort_keys=True)
    print(f'[+] Wrote {a.out}: {len(cache["modules"])} modules for {", ".join(cache["features"])}')


if __name__ == '__main__':
    main()
