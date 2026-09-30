"""Per-recording measurements and their aggregation across recordings."""
from dataclasses import dataclass

import numpy as np
from scipy.ndimage import median_filter
from scipy.signal import find_peaks, resample_poly

from . import config
from .audio import Recording
from .config import BANDS, C, GUARD_S
from .dsp import bandpass, db, octave, smooth
from .spatial import foa_direction, foa_intensity


@dataclass
class Analysis:
    name: str
    kind: str                       # "impulsive" (clap) or "sustained" (yell)
    onset: int
    decay_start: int
    decay_end: int
    noise_db: float
    peak_db: float
    rt60: dict                      # band -> seconds (or None)
    edt: dict
    rt_method: dict
    drr_db: float | None = None
    c50_db: float | None = None
    direct_prominence_db: float | None = None
    ild_db: float | None = None             # left minus right level at the onset (1-10 kHz)
    side: int = 0                           # +1 right-channel end, -1 left-channel end, 0 uncertain
    doa_az_deg: float | None = None         # from Spatial Audio (FOA), phone frame
    doa_el_deg: float | None = None
    doa_strength: float | None = None
    reflection_map: list | None = None      # [(ms after onset, az, el, level dB, strength)], first 80 ms
    distance_m: float | None = None
    distance_raw_m: float | None = None     # before calibration
    env_t: np.ndarray | None = None
    env_db: np.ndarray | None = None
    mode_spectrum: tuple | None = None      # (freqs, whitened dB)
    flutter_ac: tuple | None = None         # (lags s, autocorr)

    @property
    def distance_reliable(self) -> bool:
        return self.direct_prominence_db is not None and self.direct_prominence_db >= config.DIRECT_MIN_DB


def detect_event(rec: Recording):
    sr, x = rec.sr, bandpass(rec.mono, rec.sr, 100, 10000)
    g = int(GUARD_S * sr)
    e10 = smooth(x * x, sr, 0.010)
    valid = slice(g, len(x) - g)
    peak = g + int(np.argmax(e10[valid]))
    pre = e10[g:max(g + 1, peak - int(0.2 * sr))]
    noise = np.median(pre) if len(pre) > 0.1 * sr else np.percentile(e10[valid], 5)
    noise_db, peak_db = db(noise), db(e10[peak])

    # onset: last point before the peak that is still near the noise floor, refined with a 0.5 ms envelope
    below = np.flatnonzero(db(e10[g:peak]) < noise_db + 10)
    coarse = g + (below[-1] if len(below) else 0)
    e05 = smooth(x * x, sr, 0.0005)
    search = e05[coarse:peak + 1]
    thr = max(noise * 10 ** 2.0, 0.05 * search.max())
    onset = coarse + int(np.argmax(search > thr))

    # Excitation length: time for the 50 ms envelope to fall 10 dB below its maximum, minus the time the
    # room's own decay would need for 10 dB. A clap leaves only reverb, so the difference is ~0.
    e50 = db(smooth(x * x, sr, 0.050))
    seg = e50[onset:len(x) - g]
    top = seg.max()
    t10 = int(np.flatnonzero(seg >= top - 10)[-1])
    later = np.flatnonzero((seg[t10:] <= top - 10) & (seg[t10:] >= max(top - 35, noise_db + 10)))
    slope = np.polyfit(later / sr, seg[t10 + later], 1)[0] if len(later) > 0.05 * sr else -40.0
    reverb_10db = 10.0 / max(-slope, 5.0)
    excitation = t10 / sr - reverb_10db
    kind = "impulsive" if excitation < config.IMPULSIVE_MAX_S else "sustained"

    # free decay: from the envelope peak for claps, after the last loud moment (within 3 dB of max) for yells
    decay_start = peak if kind == "impulsive" else onset + int(np.flatnonzero(seg >= top - 3)[-1])
    quiet = np.flatnonzero(e50[decay_start:len(x) - g] < noise_db + 6)
    decay_end = decay_start + int(quiet[0]) if len(quiet) else len(x) - g
    return onset, decay_start, decay_end, noise, noise_db, peak_db, kind


def schroeder_rt(e: np.ndarray, sr: int, noise: float):
    """RT60 and EDT from a band-limited energy decay, noise-compensated (Chu) and truncated."""
    sm = smooth(e, sr, 0.02)
    below = np.flatnonzero(sm < 2 * noise)
    cut = int(below[0]) if len(below) else len(e)
    if cut < 0.05 * sr:
        return None, None, None
    edc = np.cumsum((e[:cut] - noise)[::-1])[::-1]
    edc = np.maximum(edc, edc[0] * 1e-9)
    edc_db = db(edc / edc[0])
    t = np.arange(cut) / sr

    def fit(hi, lo):
        idx = np.flatnonzero((edc_db <= hi) & (edc_db >= lo))
        if len(idx) < 0.02 * sr:
            return None, 0.0
        p = np.polyfit(t[idx], edc_db[idx], 1)
        pred = np.polyval(p, t[idx])
        r2 = 1 - np.sum((edc_db[idx] - pred) ** 2) / max(np.sum((edc_db[idx] - edc_db[idx].mean()) ** 2), 1e-12)
        return (-60.0 / p[0] if p[0] < 0 else None), r2

    depth = edc_db[int(0.95 * cut)]
    rt, method = None, None
    for name, lo in (("T30", -35), ("T20", -25), ("T10", -15)):
        if depth <= lo - 2:
            rt, r2 = fit(-5, lo)
            if rt is not None and r2 > 0.95:
                method = name
                break
            rt = None
    edt, _ = fit(0, -10)
    return rt, edt, method


def analyse(rec: Recording) -> Analysis:
    sr = rec.sr
    onset, d0, d1, noise, noise_db, peak_db, kind = detect_event(rec)
    g = int(GUARD_S * sr)
    noise_slice = slice(g, max(g + 1, onset - int(0.05 * sr)))

    rt60, edt, how = {}, {}, {}
    for fc in BANDS:
        e = octave(rec.mono, sr, fc) ** 2
        nb = e[noise_slice].mean() if noise_slice.stop - noise_slice.start > 0.1 * sr else np.percentile(smooth(e, sr, 0.02), 5)
        rt60[fc], edt[fc], how[fc] = schroeder_rt(e[d0:len(e) - g], sr, nb)

    a = Analysis(rec.name, kind, onset, d0, d1, noise_db, peak_db, rt60, edt, how)

    x = bandpass(rec.mono, sr, 100, 10000)
    env = db(smooth(x * x, sr, 0.005))
    s = max(0, onset - int(0.05 * sr))
    a.env_t = (np.arange(s, min(len(x), onset + int(2.5 * sr))) - onset) / sr
    a.env_db = env[s:s + len(a.env_t)] - env[onset:onset + int(0.2 * sr)].max()

    # which side of the phone the sound came from (level difference of the first 10 ms)
    w0, w1 = config.SIDE_WINDOW_S
    st = bandpass(rec.stereo, sr, 1000, 10000)[:, onset + int(w0 * sr):onset + int(w1 * sr)]
    a.ild_db = float(db(np.sum(st[0] ** 2) / max(np.sum(st[1] ** 2), 1e-20)))
    a.side = 0 if abs(a.ild_db) < config.SIDE_MIN_DB else (1 if a.ild_db < 0 else -1)

    if rec.foa is not None:
        _analyse_spatial(rec, a)

    if kind == "impulsive":
        _analyse_impulse(rec, a, noise_db)
    return a


def _analyse_spatial(rec: Recording, a: Analysis) -> None:
    # The spatial track is decoded separately, so find its own onset instead of trusting the stereo one.
    fsr = rec.foa_sr
    f_on = detect_event(Recording(rec.name, rec.path, fsr, np.vstack([rec.foa[0], rec.foa[0]])))[0]
    ix, e = foa_intensity(rec.foa, fsr)
    win = 0.003 if a.kind == "impulsive" else 0.010
    a.doa_az_deg, a.doa_el_deg, a.doa_strength = foa_direction(ix, e, f_on - int(0.0005 * fsr), f_on + int(win * fsr))
    ref = e[f_on:f_on + int(0.003 * fsr)].sum() + 1e-20
    ms = int(0.001 * fsr)
    frames = []
    for k in range(80):
        a0 = f_on + k * ms
        az, el, strength = foa_direction(ix, e, a0, a0 + ms)
        frames.append((float(k), az, el, float(db(e[a0:a0 + ms].sum() / ref)), strength))
    a.reflection_map = frames


def _analyse_impulse(rec: Recording, a: Analysis, noise_db: float) -> None:
    sr, onset, d0, d1 = rec.sr, a.onset, a.decay_start, a.decay_end

    # direct-to-reverberant ratio and clarity
    y = bandpass(rec.mono, sr, 300, 10000)
    e = y * y - 10 ** (noise_db / 10)
    direct = e[max(0, onset - int(0.0005 * sr)):onset + int(0.0025 * sr)].sum()
    late = max(e[onset + int(0.0025 * sr):d1].sum(), 1e-20)
    a.drr_db = float(db(max(direct, 1e-20) / late))
    e50 = e[onset:onset + int(0.05 * sr)].sum()
    a.c50_db = float(db(max(e50, 1e-20) / max(e[onset + int(0.05 * sr):d1].sum(), 1e-20)))
    # Is there a direct sound at all? Peak of the first 2.5 ms over the typical level 5-50 ms later.
    # The DRR distance only means something when the direct sound stands out.
    env03 = smooth(y * y, sr, 0.0003)
    head = env03[onset:onset + int(0.0025 * sr)].max()
    body = np.median(env03[onset + int(0.005 * sr):onset + int(0.05 * sr)])
    a.direct_prominence_db = float(db(head / max(body, 1e-20)))

    # low-frequency spectrum of the reverberant tail (room-mode candidates)
    tail = rec.mono[d0 + int(0.01 * sr):min(d1, d0 + int(1.5 * sr))]
    if len(tail) > 0.3 * sr:
        lo_sr = 2000
        t2 = resample_poly(tail, lo_sr, sr)
        spec = np.fft.rfft(t2 * np.hanning(len(t2)), n=8192)
        f = np.fft.rfftfreq(8192, 1 / lo_sr)
        p = db(np.abs(spec) ** 2)
        keep = (f >= 20) & (f <= 320)
        f, p = f[keep], p[keep]
        bins_15hz = max(3, int(15 / (f[1] - f[0])) | 1)
        a.mode_spectrum = (f, p - median_filter(p, size=bins_15hz, mode="nearest"))

    # echo periodicity: autocorrelation of the fine-structure envelope
    y = bandpass(rec.mono, sr, 1000, 8000)
    fine = smooth(y[onset + int(0.003 * sr):onset + int(0.5 * sr)] ** 2, sr, 0.0005)
    r = fine / np.maximum(smooth(fine, sr, 0.02), 1e-20) - 1
    ac = np.correlate(r, r, "full")[len(r) - 1:]
    ac /= ac[0]
    n = int(config.FLUTTER_LAG_S[1] * sr) + 1
    a.flutter_ac = (np.arange(n) / sr, ac[:n])


def aggregate(analyses: list[Analysis]):
    """Combine recordings: median RT60 per band, averaged mode spectrum, averaged echo autocorrelation."""
    rt = {}
    for fc in BANDS:
        vals = [a.rt60[fc] for a in analyses if a.rt60[fc] is not None]
        rt[fc] = (float(np.median(vals)), float(np.std(vals)), len(vals)) if vals else (None, None, 0)

    imp = [a for a in analyses if a.mode_spectrum is not None]
    modes = None
    if imp:
        f = imp[0].mode_spectrum[0]
        spec = np.mean([a.mode_spectrum[1] for a in imp], axis=0)
        band = (f >= config.MODE_FMIN) & (f <= config.MODE_FMAX)
        min_dist = max(1, int(1.5 / (f[1] - f[0])))
        pk, pr = find_peaks(spec[band], prominence=6.0 if len(imp) > 1 else 8.0, distance=min_dist)
        strongest = np.sort(np.argsort(pr["prominences"])[::-1][:config.MAX_MODE_PEAKS])
        modes = dict(freqs=f, spec=spec, peaks=f[band][pk[strongest]], prominence=pr["prominences"][strongest])

    flutter = None
    acs = [a.flutter_ac for a in analyses if a.flutter_ac is not None]
    if acs:
        lags = acs[0][0]
        ac = np.mean([x[1] for x in acs], axis=0)
        sr_lag = 1 / (lags[1] - lags[0])
        rng = (lags >= config.FLUTTER_LAG_S[0]) & (lags <= config.FLUTTER_LAG_S[1])
        base = ac[rng]
        mad = np.median(np.abs(base - np.median(base))) + 1e-9
        pk, pr = find_peaks(base, prominence=4 * mad, distance=int(0.002 * sr_lag))
        order = np.argsort(pr["prominences"])[::-1][:4]
        cand = [(float(lags[rng][pk[i]] * C / 2), float(pr["prominences"][i] / (4 * mad))) for i in order]
        flutter = dict(lags=lags, ac=ac, candidates=cand)
    return rt, modes, flutter
