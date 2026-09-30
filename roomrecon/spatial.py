"""Direction analysis of first-order ambisonics (ACN channel order W Y Z X, SN3D)."""
import math

import numpy as np

from .dsp import bandpass


def foa_intensity(foa: np.ndarray, sr: int, lo: float = 500, hi: float = 8000):
    """Band-limited active intensity components (x, y, z) and energy of an FOA signal."""
    W, Y, Z, X = bandpass(foa, sr, lo, hi)
    return np.stack([W * X, W * Y, W * Z]), 0.5 * (W ** 2 + X ** 2 + Y ** 2 + Z ** 2)


def foa_direction(ix: np.ndarray, e: np.ndarray, a: int, b: int):
    """Direction of the intensity summed over samples a:b.

    Azimuth 0 = the phone's +X axis, +90 = +Y (left); strength 1 = one clean plane wave, 0 = diffuse."""
    v = ix[:, a:b].sum(axis=1)
    en = e[a:b].sum() + 1e-20
    az = math.degrees(math.atan2(v[1], v[0]))
    el = math.degrees(math.atan2(v[2], math.hypot(v[0], v[1])))
    return az, el, float(np.linalg.norm(v) / en)
