"""splash_hxtra.py - the stock boot picture (HXStomp_Splash) with "HX STOMP" relabelled "HXtra STOMP".

The letters are lifted off the picture, the background under them filled in from around them, and "HX", the "tra" drawn here
in the same 3 px white strokes, and "STOMP" laid back on it, centred. Made from the firmware's own pixels at build time, so the
repo holds no Line 6 artwork.
"""
import numpy as np

TOP = 148                       # the text band: from here to the bottom of the 320x181 picture
HX, STOMP = (48, 128), (144, 272)       # the stock columns of "HX" and "STOMP", anti-aliasing included
INK = 255.0                     # the letters are white
CAP, BASE = 151.0, 180.0        # cap line and baseline: the top and bottom edges of the stock capitals
XH = 158.0                      # the x-height, 0.75 of the capitals
HALF = 1.35                     # half a stroke
SS = 8                          # supersampling per axis
GAP, SPACE = 6, 20              # "X" to "t"; the word space, as stock "X" to "S"
KERN = 3                        # between the lowercase letters


def bezier(p0, p1, p2, p3, n=24):
    t = np.linspace(0, 1, n)[:, None]
    return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * np.array(p3)


def ellipse(cx, cy, rx, ry, n=64):
    a = np.linspace(0, 2 * np.pi, n)
    return np.stack([cx + rx * np.cos(a), cy + ry * np.sin(a)], 1)


def letters():
    """[(width, [centre-line polylines])] of "t", "r" and "a", x from 0, y in picture rows."""
    # Stems and bars on pixel centres, so they come out one solid pixel with soft edges, as the stock letters do
    top, foot = XH + 1.5, BASE - 1.5
    t = [np.array([[3.5, CAP + 2.5], [3.5, foot - 3.5]]),
         bezier(np.array([3.5, foot - 3.5]), np.array([3.5, foot]), np.array([5.5, foot]), (8.5, foot)),
         np.array([[1.2, top], [8.8, top]])]
    r = [np.array([[1.5, top], [1.5, foot]]),
         bezier(np.array([1.5, top + 6.5]), np.array([2.5, top]), np.array([5.5, top - 0.2]), (9.0, top + 0.3))]
    rx = 6.5
    a = [ellipse(1.5 + rx, (XH + BASE) / 2, rx, (BASE - XH) / 2 - HALF + 0.2),
         np.array([[1.5 + 2 * rx, top], [1.5 + 2 * rx, foot]])]
    return [(10, t), (10, r), (16, a)]


def stroke(lines, w, h, x0, y0):
    """Coverage (h, w) of the polylines drawn HALF thick on the pixels from (x0, y0), supersampled."""
    ys, xs = np.mgrid[0:h * SS, 0:w * SS]
    px, py = x0 + (xs + 0.5) / SS, y0 + (ys + 0.5) / SS
    d = np.full(px.shape, np.inf)
    for pl in lines:
        for (ax, ay), (bx, by) in zip(pl[:-1], pl[1:]):
            vx, vy = bx - ax, by - ay
            k = np.clip(((px - ax) * vx + (py - ay) * vy) / max(vx * vx + vy * vy, 1e-9), 0, 1)
            d = np.minimum(d, np.hypot(px - ax - k * vx, py - ay - k * vy))
    return (d <= HALF).reshape(h, SS, w, SS).mean((1, 3))


def lift(band):
    """(background, alpha) of the text band: the letters' pixels filled in from their neighbours, and how white each pixel is."""
    lum = band.mean(2)
    hole = lum > 100
    for _ in range(2):                                  # the letters' anti-aliased edges
        hole[1:] |= hole[:-1]; hole[:-1] |= hole[1:]; hole[:, 1:] |= hole[:, :-1]; hole[:, :-1] |= hole[:, 1:]
    bg = band.copy()
    bg[hole] = band[~hole].mean(0)
    for _ in range(400):                                # Laplace fill: the background is smooth and faint here
        p = np.pad(bg, ((1, 1), (1, 1), (0, 0)), mode='edge')
        avg = (p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:]) / 4
        bg[hole] = avg[hole]
    alpha = np.where(hole, ((band - bg) / np.maximum(INK - bg, 1)).mean(2), 0).clip(0, 1)
    return bg, alpha


def layout(w):
    """(x of "HX", [x of "t", "r", "a"], x of "STOMP") in a picture w wide, the line centred."""
    widths = [lw for lw, _ in letters()]
    width = (HX[1] - HX[0]) + GAP + sum(widths) + KERN * (len(widths) - 1) + SPACE + (STOMP[1] - STOMP[0])
    hx = (w - width) // 2
    xs = [hx + HX[1] - HX[0] + GAP]
    for lw in widths[:-1]:
        xs.append(xs[-1] + lw + KERN)
    return hx, xs, xs[-1] + widths[-1] + SPACE


def relabel(rows):
    """Rows of (r, g, b) of the stock HXStomp_Splash, relabelled "HXtra STOMP"."""
    pic = np.array(rows, dtype=np.float64)
    h, w = pic.shape[:2]
    bg, alpha = lift(pic[TOP:])
    hx, xs, stomp = layout(w)
    ink = np.zeros_like(alpha)
    ink[:, hx:hx + HX[1] - HX[0]] = alpha[:, HX[0]:HX[1]]
    ink[:, stomp:stomp + STOMP[1] - STOMP[0]] = alpha[:, STOMP[0]:STOMP[1]]
    for x, (_, lines) in zip(xs, letters()):
        ink[:, x:] = np.maximum(ink[:, x:], stroke(lines, w - x, h - TOP, 0, TOP))
    pic[TOP:] = bg * (1 - ink[..., None]) + INK * ink[..., None]
    return [[tuple(int(round(v)) for v in px) for px in row] for row in pic.clip(0, 255)]
