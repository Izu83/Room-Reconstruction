"""Command line: python -m roomrecon [extract | calibrate] [inputs] [options]

  python -m roomrecon                      reconstruct from data/audios (or data/videos)
  python -m roomrecon path/to/files ...    reconstruct from the given recordings or folders
  python -m roomrecon extract              write the stereo track of data/videos/* to data/audios
  python -m roomrecon calibrate            fit corrections against data/ground_truth/room_coordinates.txt
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from . import config
from .analysis import aggregate, analyse
from .audio import discover_inputs, extract_videos, load_recording
from .calibration import load_calibration, run_calibration
from .config import BANDS, settings
from .model import RoomModel, eyring_absorption, fit_room, locate_sources
from .preview import write_preview
from .report import make_report, material_hint, summary_text
from .synthesis import dry_clap, synth_rir
from .truth import compare_truth, parse_truth


def build_parser():
    ap = argparse.ArgumentParser(prog="roomrecon", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="*", help="audio/video files or folders (default: data/audios, else data/videos)")
    ap.add_argument("-o", "--out", default=str(config.OUTPUT_DIR), help="output folder")
    ap.add_argument("--truth", default=str(config.TRUTH_FILE), help="ground-truth file for evaluation / calibration")
    ap.add_argument("--up-axis", default="y", choices="xyz", help="vertical axis in the truth file")
    ap.add_argument("--no-calibration", action="store_true", help="ignore config/calibration.json")
    ap.add_argument("--same-room", action="store_true",
                    help="calibrate: also copy this room's size/absorption into the priors (re-analysing the same room only)")
    ap.add_argument("--use-modes", action="store_true", help="also fit low-frequency room-mode peaks (unreliable with phone mics)")
    ap.add_argument("--seed", type=int, default=0)
    return ap


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv.pop(0) if argv and argv[0] in ("extract", "calibrate", "reconstruct") else "reconstruct"
    args = build_parser().parse_args(argv)
    if command == "extract":
        extract_videos()
        return
    reconstruct(args, calibrate=command == "calibrate")


def reconstruct(args, calibrate=False):
    settings.use_modes = args.use_modes
    if not args.inputs and not any(config.AUDIO_DIR.glob("*.wav")) and config.VIDEO_DIR.exists():
        print("Extracting audio from data/videos ...")
        extract_videos()
    paths = discover_inputs(args.inputs)
    if not paths:
        sys.exit("No input recordings found.")
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"Analysing {len(paths)} recording(s)...")
    analyses, recs = [], []
    for p in paths:
        rec = load_recording(p)
        a = analyse(rec)
        recs.append(rec)
        analyses.append(a)
        rts = " ".join(f"{a.rt60[b]:.2f}" if a.rt60[b] else "  - " for b in BANDS)
        spatial = "  +spatial" if rec.foa is not None else ""
        print(f"  {a.name:>8}  {a.kind:<9}  onset {a.onset / rec.sr:5.2f}s  SNR {a.peak_db - a.noise_db:4.0f} dB  "
              f"RT60[{'/'.join(map(str, BANDS))}] = {rts}{spatial}")
    sr = recs[0].sr

    rt, modes, flutter = aggregate(analyses)
    model = RoomModel(rt, modes, flutter)
    if model.rt_mid is None:
        sys.exit("Could not measure a reverberation time - recordings too noisy or too short.")
    if flutter:
        print("Echo-periodicity distances (m, strength): " + ", ".join(f"{d:.2f} ({s:.1f})" for d, s in flutter["candidates"]))

    truth = parse_truth(Path(args.truth))
    if calibrate:
        L, samples, alternatives, calibration = run_calibration(analyses, rt, modes, flutter, truth or {}, args)
    else:
        calibration = None if args.no_calibration else load_calibration()
        if calibration:
            config.apply_calibration(calibration)
            print(f"Using {config.CALIBRATION_FILE.relative_to(config.ROOT)} ({calibration.get('mode', 'room')} mode; "
                  f"--no-calibration to ignore)")
        print("Fitting room geometry...")
        L, samples, alternatives = fit_room(model, args.seed)
    lo, hi = np.percentile(samples, 5, axis=0), np.percentile(samples, 95, axis=0)
    vols = np.prod(samples, axis=1)
    alpha = {b: eyring_absorption(L, rt[b][0]) for b in BANDS if rt[b][0]}
    alpha_mid = eyring_absorption(L, model.rt_mid)
    rc = locate_sources(analyses, L, model.rt_mid)

    same_room = bool(calibration) and calibration.get("mode", "room") == "room"
    if not calibration:
        cal_text = "off (default priors)"
    elif same_room:
        cal_text = (f"SAME-ROOM (priors copied from {Path(calibration.get('truth_file', '?')).name} - wrong for other rooms), "
                    f"distance x{calibration['distance_scale']:.2f}")
    else:
        cal_text = f"general (generic size priors), distance x{calibration['distance_scale']:.2f}"
    notes = [
        f"Room (L x W x H): {L[0]:.2f} x {L[1]:.2f} x {L[2]:.2f} m   90% ranges: "
        f"L {lo[0]:.1f}-{hi[0]:.1f}, W {lo[1]:.1f}-{hi[1]:.1f}, H {lo[2]:.1f}-{hi[2]:.1f} m",
        f"Volume {np.prod(L):.1f} m3 (90%: {np.percentile(vols, 5):.0f}-{np.percentile(vols, 95):.0f})   "
        f"floor area {L[0] * L[1]:.1f} m2   RT60(mid) {model.rt_mid:.2f} s   mean absorption {alpha_mid:.3f}   critical distance {rc:.2f} m",
        "Calibration: " + cal_text,
        "Measured from audio: RT60, surface character, ceiling height (floor-ceiling echo). Floor length/width are "
        + ("taken from the calibration room's proportions." if same_room
           else "not measurable from these recordings (generic priors, wide ranges)."),
    ] + ["Surfaces: " + n for n in material_hint(rt)]
    truth_lines = compare_truth(truth, L, analyses, args.up_axis) if truth else []

    # impulse response of the reconstructed room + a clap played in it
    mic = np.array([0.4 * L[0], 0.45 * L[1], 1.0])
    dists = [a.distance_m for a in analyses if a.distance_m]
    d = float(np.median(dists)) if dists else 2.0
    src = np.clip(mic + np.array([d, 0, 0.5]), 0.2, np.array(L) - 0.2)
    rir = synth_rir(L, rt, sr, src, mic, alpha_mid)
    wavfile.write(str(outdir / "reconstructed_room_ir.wav"), sr, rir.astype(np.float32))
    clap = np.convolve(dry_clap(sr), rir)
    clap = 0.9 * clap / np.max(np.abs(clap))
    wavfile.write(str(outdir / "clap_in_reconstructed_room.wav"), sr, clap.astype(np.float32))

    report = make_report(outdir, analyses, rt, modes, flutter, L, samples, notes + truth_lines)

    result = {
        "room": {"length_m": L[0], "width_m": L[1], "height_m": L[2], "volume_m3": float(np.prod(L)),
                 "floor_area_m2": L[0] * L[1],
                 "ci90": {"length": [lo[0], hi[0]], "width": [lo[1], hi[1]], "height": [lo[2], hi[2]],
                          "volume": [float(np.percentile(vols, 5)), float(np.percentile(vols, 95))]},
                 "alternative_optima": alternatives},
        "acoustics": {"rt60_s": {str(b): rt[b][0] for b in BANDS}, "rt60_std_s": {str(b): rt[b][1] for b in BANDS},
                      "eyring_absorption": {str(b): v for b, v in alpha.items()},
                      "rt60_mid_s": model.rt_mid, "absorption_mid": alpha_mid,
                      "critical_distance_m": rc,
                      "mode_peaks_hz": modes["peaks"].tolist() if modes is not None else [],
                      "echo_distances_m": flutter["candidates"] if flutter else [],
                      "surface_notes": material_hint(rt)},
        "recordings": [{"name": a.name, "kind": a.kind, "onset_s": a.onset / sr,
                        "rt60_s": {str(b): a.rt60[b] for b in BANDS}, "rt_method": {str(b): a.rt_method[b] for b in BANDS},
                        "edt_s": {str(b): a.edt[b] for b in BANDS},
                        "drr_db": a.drr_db, "c50_db": a.c50_db,
                        "source_side": a.side, "stereo_level_difference_db": a.ild_db,
                        "spatial_direction": ({"azimuth_deg": a.doa_az_deg, "elevation_deg": a.doa_el_deg,
                                               "strength": a.doa_strength, "reflection_map": a.reflection_map}
                                              if a.doa_az_deg is not None else None),
                        "source_distance_m": a.distance_m,
                        "source_distance_uncalibrated_m": a.distance_raw_m,
                        "direct_prominence_db": a.direct_prominence_db,
                        "source_distance_reliable": a.distance_reliable if a.distance_m else None} for a in analyses],
        "calibration": calibration,
        "ground_truth_comparison": truth_lines,
    }
    (outdir / "room.json").write_text(json.dumps(result, indent=2, default=float), encoding="utf-8")
    preview = write_preview(outdir, result, truth, analyses, recs, clap, sr, args.up_axis, calibration)

    text = summary_text(notes, analyses, truth_lines, calibration, args.truth, {
        "3D preview:": preview, "Report:": report,
        "Data:": outdir / "room.json",
        "Audio:": f"{outdir / 'reconstructed_room_ir.wav'}, {outdir / 'clap_in_reconstructed_room.wav'}",
    })
    (outdir / "summary.txt").write_text(text, encoding="utf-8")
    print()
    print(text)
