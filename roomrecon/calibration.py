"""Calibration against a room with known geometry (config/calibration.json)."""
import json
import math
import sys
from pathlib import Path

import numpy as np

from . import config
from .config import CALIBRATED_SIGMA, settings
from .model import RoomModel, eyring_absorption, fit_room, locate_sources
from .truth import truth_distance, truth_room


def _relative(path) -> str:
    p = Path(path).resolve()
    try:
        return p.relative_to(config.ROOT).as_posix()
    except ValueError:
        return p.name


def load_calibration():
    if config.CALIBRATION_FILE.exists():
        return json.loads(config.CALIBRATION_FILE.read_text(encoding="utf-8"))
    return None


def run_calibration(analyses, rt, modes, flutter, truth, args):
    """Fit corrections to a room with known geometry and save them.

    Default ("general") mode keeps only what transfers to other rooms: the source-distance correction.
    The size priors stay generic, so a new room is not pulled toward the calibration room's shape.
    same_room=True also copies this room's size and absorption into the priors; only useful for
    re-analysing more recordings of the SAME room."""
    true_L = truth_room(truth, args.up_axis)
    if true_L is None:
        sys.exit(f"Calibration needs at least 'room' in {args.truth}")
    rt_mid = RoomModel(rt, modes, flutter).rt_mid

    print("Calibration: fitting with generic priors...")
    L_before, samples, alternatives = fit_room(RoomModel(rt, modes, flutter), args.seed)
    locate_sources(analyses, L_before, rt_mid)
    before = {a.name: a.distance_m for a in analyses if a.distance_m}
    L = L_before

    if args.same_room:
        cal = {
            "prior_length": [float(true_L[0]), CALIBRATED_SIGMA["length"]],
            "prior_width": [float(true_L[1]), CALIBRATED_SIGMA["width"]],
            "prior_height": [float(true_L[2]), CALIBRATED_SIGMA["height"]],
            "prior_absorption": [float(eyring_absorption(true_L, rt_mid)), CALIBRATED_SIGMA["absorption"]],
            "distance_scale": 1.0,
        }
        config.apply_calibration(cal)
        print("Calibration: fitting with this room's priors (--same-room)...")
        L, samples, alternatives = fit_room(RoomModel(rt, modes, flutter), args.seed)
        locate_sources(analyses, L, rt_mid)
    else:
        cal = {"prior_length": list(settings.prior_length), "prior_width": list(settings.prior_width),
               "prior_height": list(settings.prior_height), "prior_absorption": list(settings.prior_absorption),
               "distance_scale": 1.0}

    pairs = [(a.name, truth_distance(truth, a.name), a.distance_raw_m) for a in analyses if a.distance_raw_m]
    pairs = [(n, t, r) for n, t, r in pairs if t]
    report = []
    if pairs:
        logr = np.array([math.log(t / r) for _, t, r in pairs])
        cal["distance_scale"] = float(math.exp(np.median(logr)))
        for i, (n, t, r) in enumerate(pairs):
            # leave-one-out: scale fitted without this recording, so the error is an honest test
            others = np.delete(logr, i)
            s_loo = math.exp(np.median(others)) if len(others) else 1.0
            report.append({"recording": n, "true_m": t, "uncalibrated_m": before.get(n), "loo_calibrated_m": s_loo * r,
                           "loo_error_pct": abs(s_loo * r - t) / t * 100})
    config.apply_calibration(cal)
    locate_sources(analyses, L, rt_mid)

    cal.update({
        "mode": "room" if args.same_room else "general",
        "calibrated_on": [a.name for a in analyses],
        "truth_file": _relative(args.truth),
        "true_room_m": true_L.tolist(),
        "rt60_mid_s": rt_mid,
        "room_before_m": [float(v) for v in L_before],
        "room_after_m": [float(v) for v in L],
        "distance_check": report,
        "note": "Fitted to one room. Distance errors are leave-one-out.",
    })
    config.CALIBRATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.CALIBRATION_FILE.write_text(json.dumps(cal, indent=2), encoding="utf-8")
    print(f"Calibration saved to {config.CALIBRATION_FILE.relative_to(config.ROOT)}")
    print(f"  room before {np.round(L_before, 2).tolist()}  after {np.round(L, 2).tolist()}  true {np.round(true_L, 2).tolist()}")
    print(f"  mode {cal['mode']}, absorption prior {cal['prior_absorption'][0]:.3f}, distance scale {cal['distance_scale']:.2f}")
    for r in report:
        unc = f"{r['uncalibrated_m']:.2f}" if r["uncalibrated_m"] else "n/a"
        print(f"  {r['recording']:>8}: true {r['true_m']:.2f} m  uncalibrated {unc} m  "
              f"calibrated (leave-one-out) {r['loo_calibrated_m']:.2f} m  error {r['loo_error_pct']:.0f}%")
    return L, samples, alternatives, cal
