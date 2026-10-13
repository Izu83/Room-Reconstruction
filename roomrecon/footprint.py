"""'The people were inside the room': the floor must contain every clap position.

Each clap gives a direction (Spatial Audio, levelled with the estimated 'up') and a distance from the
direct-to-reverberant ratio. That distance is relative to the critical distance r_c = 0.057 sqrt(V / RT60),
so it grows with the room's volume; the term below therefore rescales the positions for every candidate
room instead of using fixed ones. Position uncertainty (direction ~25 deg, distance ~35 %) is handled by
Monte-Carlo samples, and the room orientation (yaw) is free.
"""
import math

import numpy as np

from .localize import level

N_SAMPLES = 200
YAWS = np.radians(np.arange(0.0, 180.0, 3.0))
DIR_SIGMA_DEG = 25.0
DIST_SIGMA = 0.35          # log-normal sigma of the DRR distance
EDGE_M = 0.35              # softness of the walls (m)
MARGIN_M = 0.2             # people stand at least this far from a wall


class SourceFootprint:
    def __init__(self, analyses, up, rt_mid, distance_scale, seed=0):
        """analyses: claps with doa_vec and drr_db; positions are stored in units of r_c."""
        pts = []
        for a in analyses:
            if a.doa_vec is None or a.drr_db is None:
                continue
            az, _ = level(a.doa_vec, up)
            g = distance_scale * 10 ** (-a.drr_db / 20)          # distance / r_c
            pts.append((math.radians(az), g))
        self.n = len(pts)
        self.rt_mid = rt_mid
        if self.n < 2:
            return
        rng = np.random.default_rng(seed)
        az = np.array([p[0] for p in pts])[None, :] + np.radians(DIR_SIGMA_DEG) * rng.normal(size=(N_SAMPLES, self.n))
        g = np.array([p[1] for p in pts])[None, :] * np.exp(DIST_SIGMA * rng.normal(size=(N_SAMPLES, self.n)))
        x, y = g * np.cos(az), g * np.sin(az)                    # (S, n), phone at the origin
        # extents of {phone, sources} along the two room axes for every yaw: (S, n_yaw)
        c, s = np.cos(YAWS)[None, None, :], np.sin(YAWS)[None, None, :]
        u = x[:, :, None] * c + y[:, :, None] * s
        v = -x[:, :, None] * s + y[:, :, None] * c
        zero = np.zeros((N_SAMPLES, 1, len(YAWS)))
        u, v = np.concatenate([u, zero], 1), np.concatenate([v, zero], 1)
        self.e1 = u.max(1) - u.min(1)
        self.e2 = v.max(1) - v.min(1)

    def active(self):
        return self.n >= 2

    def extents_m(self, L):
        rc = 0.057 * math.sqrt(L[0] * L[1] * L[2] / self.rt_mid)
        return self.e1 * rc + 2 * MARGIN_M, self.e2 * rc + 2 * MARGIN_M

    def loglik(self, L):
        """log P(all sources fit inside an L x W floor for some orientation)."""
        e1, e2 = self.extents_m(L)
        sig = lambda z: 1 / (1 + np.exp(-z / EDGE_M))
        fit = sig(L[0] - e1) * sig(L[1] - e2)
        p = fit.max(axis=1).mean()                               # best orientation, averaged over samples
        return math.log(p + 1e-3)
