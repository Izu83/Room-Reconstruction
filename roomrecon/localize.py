"""Where the sounds came from: Spatial Audio directions, levelled to the room, checked against ground truth.

Measured on the test room (8 recordings, 4 positions):
  - direct-sound direction from the ambisonics track: ~18 deg median error after one rotation
    (shuffled positions: ~55 deg), i.e. the directions carry real information
  - "up" from the plane of the source directions (people stand around the phone at a similar height):
    ~25-40 deg from the truth-based estimate, correct sign. Needs >= 3 sources spread around the phone.
"""
import math

import numpy as np

from .truth import truth_source


def unit(az_deg, el_deg):
    az, el = math.radians(az_deg), math.radians(el_deg)
    return np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])


def angle_deg(a, b):
    return math.degrees(math.acos(float(np.clip(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)), -1, 1))))


def estimate_up(analyses):
    """Normal of the plane the source directions lie in, pointing so the sources are (slightly) above.

    Returns (up vector in the ambisonics frame, flatness) or (None, None) with fewer than 3 sources.
    flatness = smallest / middle eigenvalue: small means a well-defined plane."""
    vs = [(a.doa_vec, a.doa_strength) for a in analyses if a.doa_vec is not None]
    if len(vs) < 3:
        return None, None
    V = np.array([v for v, _ in vs])
    w = np.array([s for _, s in vs])
    ev, vec = np.linalg.eigh((V * w[:, None]).T @ V)
    up = vec[:, 0]
    if (V @ up).mean() < 0:
        up = -up
    return up, float(ev[0] / max(ev[1], 1e-12))


def level(v, up):
    """Azimuth / elevation of v in a levelled frame (azimuth 0 = the ambisonics +X axis projected)."""
    x = np.array([1.0, 0.0, 0.0])
    x_h = x - (x @ up) * up
    if np.linalg.norm(x_h) < 1e-6:
        x_h = np.array([0.0, 1.0, 0.0]) - up[1] * up
    x_h /= np.linalg.norm(x_h)
    y_h = np.cross(up, x_h)
    return math.degrees(math.atan2(v @ y_h, v @ x_h)), math.degrees(math.asin(float(np.clip(v @ up, -1, 1))))


def _kabsch(A, B, w=None):
    """Rotation R (det +1) minimising sum w |R a - b|^2 for unit vectors a (rows of A) and b."""
    w = np.ones(len(A)) if w is None else w
    H = (A * w[:, None]).T @ B
    U, _, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    return Vt.T @ np.diag([1, 1, d]) @ U.T


def align_to_truth(analyses, truth):
    """Rotation from truth-file coordinates to the ambisonics frame, and a leave-one-out direction check.

    The truth file may use a left-handed axis convention (a hand sketch), so both handednesses are tried.
    Returns dict(R, mirror, errors {name: deg}, median) or None."""
    phone = truth.get("phone") or truth.get("mic")
    rows = []
    for a in analyses:
        src = truth_source(truth, a.name)
        if a.doa_vec is not None and src and phone:
            d = np.array(src) - np.array(phone)
            rows.append((a.name, d / np.linalg.norm(d), a.doa_vec, a.doa_strength or 0.5))
    if len(rows) < 3:
        return None
    best = None
    for mirror in (1.0, -1.0):
        M = np.diag([mirror, 1.0, 1.0])
        A = np.array([M @ t for _, t, _, _ in rows])
        B = np.array([m for _, _, m, _ in rows])
        w = np.array([s for *_, s in rows])
        errors = {}
        for i, (name, *_ ) in enumerate(rows):
            keep = np.arange(len(rows)) != i
            if keep.sum() < 2:
                continue
            R = _kabsch(A[keep], B[keep], w[keep])
            errors[name] = angle_deg(R @ A[i], B[i])        # this recording was not used for R
        R = _kabsch(A, B, w) @ M
        med = float(np.median(list(errors.values())))
        if best is None or med < best["median"]:
            best = {"R": R, "mirror": mirror, "errors": errors, "median": med}
    return best
