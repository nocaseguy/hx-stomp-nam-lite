#!/usr/bin/env python3
"""splash_topo.py - a 320x240 boot picture: neon contour lines of a random terrain, for build.py --splash.

usage: splash_topo.py <out.png> [--seed N] [--levels N]
"""
import argparse

import numpy as np

from patch_splash import W, write_png

H = 240
SS = 3              # supersampling per axis


def terrain(rng, w, h):
    """A smooth height field in [0, 1]: Gaussian hills and pits on domain-warped coordinates."""
    y, x = np.mgrid[0:h, 0:w].astype(np.float64) / SS
    for _ in range(2):
        a, b, p, q = rng.uniform(0.01, 0.03, 2).tolist() + rng.uniform(0, 2 * np.pi, 2).tolist()
        x, y = x + 9 * np.sin(y * a + p), y + 9 * np.sin(x * b + q)
    z = np.zeros_like(x)
    for _ in range(18):
        cx, cy = rng.uniform(-40, W + 40), rng.uniform(-40, H + 40)
        s, amp = rng.uniform(22, 75), rng.choice([-1, 1]) * rng.uniform(0.5, 1.0)
        z += amp * np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * s * s))
    return (z - z.min()) / (z.max() - z.min())


def palette(t):
    """Neon cosine palette: cycles through magenta, cyan, lime and orange as t grows by 1."""
    d = np.array([0.67, 0.33, 0.0])
    return 0.5 + 0.5 * np.cos(2 * np.pi * (t[..., None] + d))


def render(seed, levels):
    rng = np.random.default_rng(seed)
    w, h = W * SS, H * SS
    f = terrain(rng, w, h) * levels
    gy, gx = np.gradient(f)
    slope = np.hypot(gx, gy) * SS + 1e-6                       # level units per output pixel
    k = np.round(f)
    dist = np.abs(f - k) / slope                                # output pixels to the nearest contour
    major = (k.astype(int) % 5) == 0
    half = np.where(major, 1.1, 0.45)
    ink = np.clip(half + 0.5 - dist, 0, 1) * np.where(major, 1.0, 0.75)
    x = np.arange(w)[None, :] / w
    hue = palette(f / levels * 1.7 + 0.35 * x + 0.1)
    glow = 0.05 + 0.05 * (np.floor(f) % 2)                      # faint alternating bands between lines
    rgb = hue * glow[..., None] + hue * ink[..., None]
    rgb = rgb.reshape(H, SS, W, SS, 3).mean(axis=(1, 3))
    fade = np.clip((np.arange(H) - 185) / 40, 0, 1) * 0.5     # darker behind the text at the bottom
    rgb *= (1 - fade)[:, None, None]
    return [[tuple(int(v) for v in px) for px in row] for row in np.clip(rgb * 255 + 0.5, 0, 255).astype(np.uint8)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('png')
    ap.add_argument('--seed', type=int, default=23)
    ap.add_argument('--levels', type=int, default=34)
    a = ap.parse_args()
    write_png(a.png, render(a.seed, a.levels))
    print(f'[+] Wrote {a.png} ({W}x{H}, seed {a.seed})')


if __name__ == '__main__':
    main()
