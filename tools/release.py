#!/usr/bin/env python3
"""release.py - publish an HXtra release: a GitHub release of the commit you're on, with the web page's M4 code
(tools/m4cache.py) attached, which the Pages workflow (.github/workflows/pages.yml) then publishes with the page.

usage: release.py <HX_Stomp_v3.80.0_0x103966115.hxf> <tag> [--notes "text"] [--dry-run]

Run it on a Mac (the code is assembled with clang) from a clean checkout of a pushed commit, usually main. It refuses a tag
the boot text doesn't show when that text is a version (tools/features/splash.py TEXT). --dry-run makes build/m4cache.json
and stops before the release.
"""
import argparse
import json
import os
import re
import subprocess

import m4cache
from features import splash

ROOT = m4cache.ROOT


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def repo(url):
    """owner/name of a GitHub remote URL."""
    m = re.search(r'github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$', url)
    if not m:
        raise SystemExit(f'release: {url} is not a GitHub repository')
    return m.group(1)


def check_version(tag, text):
    if not re.fullmatch(r'v\d+\.\d+\.\d+(-[\w.]+)?', tag):
        raise SystemExit(f'release: {tag} is not a version tag such as v1.0.0')
    if re.match(r'v\d', text) and text != tag:
        raise SystemExit(f'release: the boot text says {text} (tools/features/splash.py TEXT), not {tag}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('stock', help='the stock HX Stomp 3.80.0 .hxf')
    ap.add_argument('tag', help='the release, e.g. v1.0.0')
    ap.add_argument('--notes', help='the release notes (default: generated from the pull requests since the last one)')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    check_version(a.tag, splash.TEXT)
    if git('status', '--porcelain', '--untracked-files=no'):
        raise SystemExit('release: commit or put away your changes first: the release is of the commit, not the files')
    sha = git('rev-parse', 'HEAD')
    if not git('branch', '-r', '--contains', sha):
        raise SystemExit('release: push this commit first')
    if git('rev-parse', '-q', '--verify', f'refs/tags/{a.tag}'):
        raise SystemExit(f'release: {a.tag} exists already')
    out = os.path.join(ROOT, 'build', 'm4cache.json')
    cache = m4cache.make(a.stock, a.tag)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w') as f:
        json.dump(cache, f, separators=(',', ':'), sort_keys=True)
    print(f'[+] Wrote {out}: {len(cache["modules"])} modules for {", ".join(cache["features"])}')
    if a.dry_run:
        return
    cmd = ['gh', 'release', 'create', a.tag, out, '-R', repo(git('remote', 'get-url', 'origin')), '--target', sha,
           '--title', f'HXtra {a.tag}', *(['--notes', a.notes] if a.notes else ['--generate-notes'])]
    subprocess.run(cmd, cwd=ROOT, check=True)
    print(f'[+] Released {a.tag}; the Pages workflow publishes the page for it')


if __name__ == '__main__':
    main()
