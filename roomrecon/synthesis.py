"""Impulse response of the reconstructed room and a synthetic dry clap to play in it."""
import math

import numpy as np

from .config import C
from .dsp import bandpass, octave


def synth_rir(L, rt, sr, src, mic, alpha_mid, length_s=None):
    """Image sources for the first 80 ms plus a noise tail decaying with the measured RT60 per band."""
    rt_vals = {b: v[0] for b, v in rt.items() if v[0]}
    rt_max = max(rt_vals.values()) if rt_vals else 1.0
    n = int((length_s or min(3.0, 1.2 * rt_max)) * sr)
    L, src, mic = np.asarray(L, float), np.asarray(src, float), np.asarray(mic, float)
    h = np.zeros(n)
    beta = math.sqrt(1 - alpha_mid)
    t_early = 0.08
    order = int(t_early * C / min(L)) + 1
    r = np.arange(-order, order + 1)
    nx, ny, nz = np.meshgrid(r, r, r, indexing="ij")
    for px in (0, 1):
        for py in (0, 1):
            for pz in (0, 1):
                img = np.stack([(1 - 2 * px) * src[0] + 2 * nx * L[0],
                                (1 - 2 * py) * src[1] + 2 * ny * L[1],
                                (1 - 2 * pz) * src[2] + 2 * nz * L[2]], -1)
                d = np.linalg.norm(img - mic, axis=-1)
                refl = np.abs(nx - px) + np.abs(nx) + np.abs(ny - py) + np.abs(ny) + np.abs(nz - pz) + np.abs(nz)
                k = np.round(d / C * sr).astype(int)
                m = (d / C <= t_early) & (k < n)
                np.add.at(h, k[m], beta ** refl[m] / np.maximum(d[m], 0.1))

    direct_d = float(np.linalg.norm(src - mic))
    rng = np.random.default_rng(1)
    t = np.arange(n) / sr
    tail = np.zeros(n)
    for fc, T in rt_vals.items():
        tail += octave(rng.normal(size=n), sr, fc) * np.exp(-6.91 * t / T)
    t0 = direct_d / C
    tail *= np.clip((t - t0) / 0.02, 0, 1) * np.clip((t - t0) / t_early, 0, 1) ** 0.5
    rc = 0.057 * math.sqrt(float(np.prod(L)) / (rt_vals.get(1000) or rt_max))
    e_direct = (1 / max(direct_d, 0.1)) ** 2
    tail *= math.sqrt(e_direct * (direct_d / rc) ** 2 / max(np.sum(tail ** 2), 1e-20))
    h += tail
    return h / np.max(np.abs(h))


def dry_clap(sr):
    n = int(0.004 * sr)
    rng = np.random.default_rng(7)
    c = bandpass(rng.normal(size=n * 4), sr, 400, 9000)[:n] * np.exp(-np.arange(n) / (0.0008 * sr))
    return c / np.max(np.abs(c))
