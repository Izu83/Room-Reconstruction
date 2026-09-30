"""Small signal-processing helpers."""
import math

import numpy as np
from scipy.signal import butter, sosfiltfilt


def bandpass(x: np.ndarray, sr: int, lo: float, hi: float, order: int = 4) -> np.ndarray:
    hi = min(hi, 0.45 * sr)
    sos = butter(order, [lo, hi], "bandpass", fs=sr, output="sos")
    return sosfiltfilt(sos, x, axis=-1)


def octave(x: np.ndarray, sr: int, fc: float) -> np.ndarray:
    return bandpass(x, sr, fc / math.sqrt(2), fc * math.sqrt(2))


def smooth(e: np.ndarray, sr: int, win_s: float) -> np.ndarray:
    n = max(1, int(win_s * sr))
    return np.convolve(e, np.ones(n) / n, "same")


def db(x, floor=1e-20):
    return 10 * np.log10(np.maximum(x, floor))
