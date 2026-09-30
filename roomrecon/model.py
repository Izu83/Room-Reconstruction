"""Shoebox room model: likelihood, fit (differential evolution + MCMC) and source distances.

Evidence used
  - Eyring reverberation  RT60 = 0.161 V / (-S ln(1 - a))  with a plausible mean absorption a
  - the most prominent echo periodicity  tau = 2 L / c  between parallel surfaces (in practice the
    floor-ceiling echo, i.e. the height)
  - optional room-mode frequencies  f = c/2 sqrt((nx/Lx)^2 + (ny/Ly)^2 + (nz/Lz)^2)  (--use-modes)
  - log-normal priors on the dimensions and the absorption
"""
import math

import numpy as np
from scipy.optimize import differential_evolution

from . import config
from .config import BOUNDS, C, MID_BANDS, settings


def lognorm_logpdf(x, median, sigma):
    # Gaussian prior on log(x). The model is optimised and sampled in log space, so no 1/x Jacobian:
    # with it the best-fit value would sit exp(-sigma^2) below the median.
    return -0.5 * ((math.log(x) - math.log(median)) / sigma) ** 2


def room_modes(L, fmax):
    ns = [np.arange(int(2 * l * fmax / C) + 1) for l in L]
    nx, ny, nz = np.meshgrid(*ns, indexing="ij")
    f = C / 2 * np.sqrt((nx / L[0]) ** 2 + (ny / L[1]) ** 2 + (nz / L[2]) ** 2)
    kind = (nx > 0).astype(int) + (ny > 0) + (nz > 0)
    m = (f > 0) & (f <= fmax)
    return f[m], np.array([0.0, 1.0, 0.5, 0.25])[kind[m]]


def eyring_absorption(L, rt):
    V = L[0] * L[1] * L[2]
    S = 2 * (L[0] * L[1] + L[0] * L[2] + L[1] * L[2])
    return 1 - math.exp(-0.161 * V / (S * rt))


class RoomModel:
    def __init__(self, rt, modes, flutter):
        mids = [rt[b][0] for b in MID_BANDS if rt[b][0]]
        self.rt_mid = float(np.mean(mids)) if mids else None
        self.peaks = modes["peaks"] if settings.use_modes and modes is not None and len(modes["peaks"]) else None
        self.peak_w = None
        if self.peaks is not None:
            w = modes["prominence"]
            self.peak_w = np.clip(w / np.median(w), 0.5, 2.0)
        # Only the most prominent echo periodicity is trusted; weaker candidates were indistinguishable
        # from random ripples of the autocorrelation when checked against a measured room.
        self.flutter = [c for c in (flutter or {}).get("candidates", []) if c[1] >= 1.0][:1]

    def loglik(self, L):
        L = np.asarray(L, float)
        for v, (lo, hi) in zip(L, BOUNDS):
            if not lo <= v <= hi:
                return -np.inf
        if L[1] > L[0]:
            return -np.inf
        ll = lognorm_logpdf(L[2], *settings.prior_height)
        ll += lognorm_logpdf(L[0], *settings.prior_length) + lognorm_logpdf(L[1], *settings.prior_width)

        if self.rt_mid:
            a = eyring_absorption(L, self.rt_mid)
            if not 0.01 < a < 0.9:
                return -np.inf
            ll += 2.0 * lognorm_logpdf(a, *settings.prior_absorption)

        if self.peaks is not None:
            f, w = room_modes(L, config.MODE_FMAX + 15)
            inb = f >= config.MODE_FMIN - 15
            f, w = f[inb], w[inb]
            if len(f) == 0:
                return -np.inf
            sig = 1.0 + 0.02 * self.peaks[:, None]
            dens = (w * np.exp(-0.5 * ((self.peaks[:, None] - f) / sig) ** 2) / (sig * math.sqrt(2 * math.pi))).sum(1) / w.sum()
            p = 0.6 * dens + 0.4 / (config.MODE_FMAX - config.MODE_FMIN)
            ll += float(np.sum(self.peak_w * np.log(p)))

        for d, strength in self.flutter:
            sig = 0.05 + 0.03 * d
            # one echo is produced by one pair of parallel surfaces -> best-matching dimension only
            match = max(sum(wn * np.exp(-0.5 * ((d - n * l) / sig) ** 2) / (sig * math.sqrt(2 * math.pi))
                            for n, wn in ((1, 0.7), (2, 0.3))) for l in L)
            ll += min(strength, 3.0) * math.log(0.5 * match + 0.5 / 14.0)
        return ll


def fit_room(model: RoomModel, seed: int = 0):
    """Best room (differential evolution, 4 restarts) and MCMC samples for uncertainty."""
    def neg(v):
        L = np.array([max(v[0], v[1]), min(v[0], v[1]), v[2]])
        ll = model.loglik(L)
        return 1e6 if not np.isfinite(ll) else -ll

    starts = []
    for s in range(4):
        r = differential_evolution(neg, BOUNDS, seed=seed + s, popsize=25, maxiter=120, tol=1e-7, polish=True)
        starts.append((r.fun, np.array([max(r.x[0], r.x[1]), min(r.x[0], r.x[1]), r.x[2]])))
    starts.sort(key=lambda t: t[0])

    # random-walk MCMC in log space from each optimum
    rng = np.random.default_rng(seed)
    samples = []
    for _, L0 in starts:
        cur, cur_ll = L0.copy(), model.loglik(L0)
        for i in range(5000):
            prop = cur * np.exp(rng.normal(0, 0.025, 3))
            if prop[1] > prop[0]:
                prop[:2] = prop[1::-1]
            ll = model.loglik(prop)
            if np.log(rng.random()) < ll - cur_ll:
                cur, cur_ll = prop, ll
            if i >= 1500 and i % 5 == 0:
                samples.append(cur.copy())
    return starts[0][1], np.array(samples), [(float(-f), L.tolist()) for f, L in starts]


def locate_sources(analyses, L, rt_mid):
    """Source distance from DRR and the critical distance r_c = 0.057 sqrt(V / RT60)."""
    rc = 0.057 * math.sqrt(float(np.prod(L)) / rt_mid) if rt_mid else None
    diag = float(np.linalg.norm(L))
    for a in analyses:
        if a.drr_db is not None and rc:
            a.distance_raw_m = float(rc * 10 ** (-a.drr_db / 20))
            a.distance_m = float(np.clip(settings.distance_scale * a.distance_raw_m, 0.3, diag))
    return rc
