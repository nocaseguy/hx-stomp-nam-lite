"""Generate a three-pluck DI or compare eight saved Floor reamp recordings offline."""
import argparse
import hashlib
import json
import wave
from pathlib import Path

import numpy as np


RATE = 48000
BLOCK = 16


def make_di(path):
    signal = np.zeros(4 * RATE)
    for start, frequency, amplitude in [(0.3, 82.41, 0.045), (1.3, 146.83, 0.12),
                                        (2.4, 98.00, 0.12)]:
        t = np.arange(round(0.85 * RATE)) / RATE
        tone = sum(np.sin(2 * np.pi * frequency * n * t) / n for n in (1, 2, 3, 5))
        env = np.minimum(t / 0.006, 1) * np.exp(-5 * t) * np.minimum((0.85-t)/0.015, 1)
        offset = round(start * RATE)
        signal[offset:offset + len(t)] = amplitude * env * tone / 2.04
    with path.open("xb") as out, wave.open(out, "wb") as wav:
        wav.setparams((1, 2, RATE, 0, "NONE", "PCM"))
        wav.writeframes(np.rint(signal * 32767).astype("<i2").tobytes())


def read_pcm(path, seconds, channels):
    with wave.open(str(path), "rb") as wav:
        width = wav.getsampwidth()
        frames = seconds * RATE
        if (wav.getframerate() != RATE or wav.getnchannels() != channels
                or wav.getnframes() != frames or width not in (2, 3, 4)):
            raise ValueError(f"{path.name}: expected {seconds}s, {channels}ch, 48 kHz integer PCM")
        raw = wav.readframes(frames)
    if len(raw) != frames * channels * width:
        raise ValueError(f"{path.name}: incomplete WAV data")
    if width == 3:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
        pcm = b[:, 0] | b[:, 1] << 8 | b[:, 2] << 16
        pcm = (pcm ^ 0x800000) - 0x800000
    else:
        pcm = np.frombuffer(raw, "<i2" if width == 2 else "<i4")
    return pcm.reshape(frames, channels).astype(float) / (1 << (8 * width - 1))


def best_lag(reference, take, first, last):
    segment = take[first:last + len(reference)]
    size = 1 << (len(segment) + len(reference) - 2).bit_length()
    cross = np.fft.irfft(np.fft.rfft(segment, size) * np.fft.rfft(reference[::-1], size), size)
    scores = cross[len(reference) - 1:len(segment)]
    return first + int(np.argmax(np.abs(scores)))


def rms(x):
    return float(np.sqrt(np.mean(x ** 2)))


def runs(mask):
    edges = np.flatnonzero(np.diff(np.r_[False, mask, False].astype(np.int8)))
    return zip(edges[::2], edges[1::2])


def compare(di_path, folder):
    source = read_pcm(di_path, 4, 1)[:, 0]
    if np.ptp(source) == 0:
        raise ValueError("DI needs a varying signal")
    results = {"di_sha256": hashlib.sha256(di_path.read_bytes()).hexdigest(), "takes": {},
               "restart_max_abs_full_scale": {}, "between_amp_relative_rms_after_gain_fit": {}}
    aligned = {}
    for amp in ("d-lux", "plexi"):
        full = {}
        for stage in ("before", "after"):
            for mode in ("bypass", "on"):
                key = f"{amp}-{stage}-{mode}"
                path = folder / (key + ".wav")
                audio = read_pcm(path, 7, 2)
                left = audio[:, 0]
                info = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "max_channel_difference": float(np.max(np.abs(left - audio[:, 1])))}
                results["takes"][key] = info
                if mode == "bypass":
                    dry_lag = best_lag(source, left, RATE // 2, 3 * RATE // 2)
                    dry = left[dry_lag:dry_lag + len(source)]
                    corr = float(np.corrcoef(dry, source)[0, 1]) if np.ptp(dry) else 0.0
                    if corr <= 0.98:
                        raise ValueError(f"{key}: dry control failed (r={corr:.6f})")
                    info.update(lag_frames=dry_lag, correlation=corr)
                    continue
                lag = best_lag(source, left, dry_lag - 2048, dry_lag + 2048)
                wet = left[lag:lag + len(source)]
                if rms(wet) < 1e-6:
                    raise ValueError(f"{key}: silent enabled return")
                aligned[amp, stage] = wet
                full[stage] = left
                info.update(lag_frames=lag, peak=float(np.max(np.abs(wet))), rms=rms(wet),
                            repeat_frames=[int(a) for a, b in runs(wet[:-BLOCK] == wet[BLOCK:])
                                           if b-a >= BLOCK and np.ptp(wet[a:b+BLOCK]) > 0.0001],
                            interior_zero_frames=[int(a) for a, b in runs(wet == 0)
                                                  if b-a >= BLOCK and a and b < len(wet)])
        results["restart_max_abs_full_scale"][amp] = float(np.max(np.abs(full["before"] - full["after"])))
    for stage in ("before", "after"):
        a, b = aligned["d-lux", stage], aligned["plexi", stage]
        gain = np.dot(a, b) / np.dot(a, a)
        results["between_amp_relative_rms_after_gain_fit"][stage] = rms(b - gain * a) / rms(b)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("generate").add_argument("di", type=Path)
    scan = sub.add_parser("compare")
    scan.add_argument("di", type=Path)
    scan.add_argument("folder", type=Path)
    args = parser.parse_args()
    if args.action == "generate":
        make_di(args.di)
    else:
        print(json.dumps(compare(args.di, args.folder), indent=2, allow_nan=False))
