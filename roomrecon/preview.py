"""Interactive 3D preview (output/room_3d.html)."""
import base64
import io
import json
import re

import numpy as np
from scipy.io import wavfile

from . import config
from .config import MID_BANDS
from .truth import truth_distance

SOURCE_COLORS = {"1": "#f28e2b", "2": "#9c4fb0", "3": "#e889b5", "4": "#8a8a8a"}
PALETTE = ["#4e79a7", "#e15759", "#59a14f", "#edc948", "#76b7b2", "#ff9da7", "#b07aa1", "#9c755f"]


def wav_b64(x, sr, max_s=None):
    x = np.asarray(x, float)
    if max_s:
        x = x[:int(max_s * sr)]
    x = x / max(np.max(np.abs(x)), 1e-9) * 0.9
    buf = io.BytesIO()
    wavfile.write(buf, sr, (x * 32767).astype(np.int16))
    return base64.b64encode(buf.getvalue()).decode("ascii")


def write_preview(outdir, result, truth, analyses, recs, clap_resynth, sr, up_axis, calibration, alignment=None):
    up = "xyz".index(up_axis)
    horiz_axes = [i for i in range(3) if i != up]

    def scene(p):  # truth-file coordinates -> scene (x, y-up, z)
        return [p[horiz_axes[0]], p[up], p[horiz_axes[1]]]

    tdata = None
    if truth and truth.get("room"):
        sources = {}
        for k, v in truth.items():
            m = re.match(r"^video (\d+)$", k)
            if m:
                sources[m.group(1)] = scene(v)
            elif k not in ("room", "phone", "mic", "phone_right"):
                sources[k] = scene(v)
        ph = truth.get("phone") or truth.get("mic")
        pr = truth.get("phone_right")
        tdata = {"room": scene(truth["room"]), "phone": scene(ph) if ph else None, "sources": sources,
                 "phone_right": scene(pr) if pr else None}

    # Spatial Audio directions in the scene: the rotation between the truth file and the ambisonics frame
    # (fitted on all recordings) turns each measured direction into room coordinates.
    R_inv = np.linalg.inv(alignment["R"]) if alignment else None
    rows = []
    for i, a in enumerate(analyses):
        num = re.search(r"(\d+)$", a.name)
        key = num.group(1) if num and tdata and num.group(1) in tdata["sources"] else a.name.lower()
        dir_scene = scene(R_inv @ a.doa_vec) if (R_inv is not None and a.doa_vec is not None) else None
        rows.append({"name": a.name, "kind": a.kind, "key": key,
                     "color": SOURCE_COLORS.get(key, PALETTE[i % len(PALETTE)]),
                     "dist_est": a.distance_m, "dist_true": truth_distance(truth, a.name) if truth else None,
                     "dist_reliable": a.distance_reliable, "side": a.side, "ild_db": a.ild_db,
                     "doa_az": a.doa_az_deg, "doa_el": a.doa_el_deg,
                     "level_az": a.level_az_deg, "level_el": a.level_el_deg,
                     "dir_scene": [float(v) for v in dir_scene] if dir_scene is not None else None,
                     "dir_err": alignment["errors"].get(a.name) if alignment else None,
                     "rt60_mid": float(np.mean([a.rt60[b] for b in MID_BANDS if a.rt60[b]] or [np.nan]))})

    clap_rec = next((r for r, a in zip(recs, analyses) if a.kind == "impulsive"), recs[0])
    ca = analyses[recs.index(clap_rec)]
    s0 = max(0, ca.onset - int(0.2 * sr))
    audio = {"original_name": clap_rec.name,
             "original": wav_b64(clap_rec.mono[s0:], sr, 3.0),
             "resynth": wav_b64(clap_resynth, sr, 3.0)}

    spatial = {"median_err": alignment["median"] if alignment else None,
               "n": sum(a.doa_vec is not None for a in analyses)}
    data = {"est": result["room"], "acoustics": {k: v for k, v in result["acoustics"].items() if k != "mode_peaks_hz"},
            "truth": tdata, "recordings": rows, "calibration": calibration, "audio": audio, "spatial": spatial}
    html = (config.TEMPLATE_DIR / "room_3d.html").read_text(encoding="utf-8")
    html = html.replace("/*__DATA__*/null", json.dumps(data, default=float).replace("</", "<\\/"))
    path = outdir / "room_3d.html"
    path.write_text(html, encoding="utf-8")
    return path
