"""Report figure (report.png), surface hints and the text summary."""
import numpy as np

from . import config
from .config import BANDS, MID_BANDS, settings
from .model import room_modes


def material_hint(rt):
    mid = np.mean([rt[b][0] for b in MID_BANDS if rt[b][0]] or [np.nan])
    hi, lo = rt[4000][0], rt[250][0]
    notes = []
    if hi and mid and hi / mid < 0.75:
        notes.append("high frequencies absorbed faster -> soft furnishings / curtains / carpet present")
    elif hi and mid:
        notes.append("flat high-frequency decay -> mostly hard surfaces (plaster, tile, glass, concrete)")
    if lo and mid and lo / mid < 0.8:
        notes.append("short low-frequency decay -> lightweight walls/panels (drywall, wood) absorbing bass")
    elif lo and mid and lo / mid > 1.2:
        notes.append("long low-frequency decay -> massive walls, little bass absorption")
    if mid and mid > 1.0:
        notes.append(f"RT60 {mid:.2f} s is long for a living space -> sparsely furnished or empty room")
    return notes


def make_report(outdir, analyses, rt, modes, flutter, L, samples, notes):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    text_h = 0.2 * (len(notes) + 1)
    fig = plt.figure(figsize=(18, 11 + text_h))
    fig.suptitle("Room reconstruction from audio", fontsize=16, weight="bold")

    ax = fig.add_subplot(2, 3, 1, projection="3d")
    x, y, z = L
    verts = [[(0, 0, 0), (x, 0, 0), (x, y, 0), (0, y, 0)], [(0, 0, z), (x, 0, z), (x, y, z), (0, y, z)],
             [(0, 0, 0), (x, 0, 0), (x, 0, z), (0, 0, z)], [(0, y, 0), (x, y, 0), (x, y, z), (0, y, z)],
             [(0, 0, 0), (0, y, 0), (0, y, z), (0, 0, z)], [(x, 0, 0), (x, y, 0), (x, y, z), (x, 0, z)]]
    ax.add_collection3d(Poly3DCollection(verts, facecolor=(0.2, 0.45, 0.8, 0.08), edgecolor="#1f4e9a", lw=1.2))
    m = max(L)
    ax.set_xlim(0, m); ax.set_ylim(0, m); ax.set_zlim(0, m)
    ax.set_xlabel("length (m)"); ax.set_ylabel("width (m)"); ax.set_zlabel("height (m)")
    ax.set_title(f"Estimated room  {x:.2f} x {y:.2f} x {z:.2f} m\nV = {x * y * z:.1f} m$^3$")
    ax.set_box_aspect((1, 1, 1))

    ax = fig.add_subplot(2, 3, 2)
    for a in analyses:
        ax.plot(BANDS, [a.rt60[b] if a.rt60[b] else np.nan for b in BANDS], "o-", alpha=0.35, lw=1, label=a.name)
    ax.plot(BANDS, [rt[b][0] if rt[b][0] else np.nan for b in BANDS], "k-o", lw=2.5, label="median")
    ax.set_xscale("log"); ax.set_xticks(BANDS); ax.set_xticklabels([str(b) for b in BANDS])
    ax.set_xlabel("octave band (Hz)"); ax.set_ylabel("RT60 (s)"); ax.set_title("Reverberation time")
    ax.grid(alpha=0.3); ax.legend(fontsize=7, ncol=2)

    ax = fig.add_subplot(2, 3, 3)
    for a in analyses:
        ax.plot(a.env_t, a.env_db, lw=0.6, alpha=0.7, label=a.name)
    ax.set_ylim(-70, 5); ax.set_xlim(-0.05, 2.5)
    ax.set_xlabel("time from onset (s)"); ax.set_ylabel("level (dB)"); ax.set_title("Energy envelopes")
    ax.grid(alpha=0.3); ax.legend(fontsize=7, ncol=2)

    ax = fig.add_subplot(2, 3, 4)
    if modes is not None:
        ax.plot(modes["freqs"], modes["spec"], lw=0.8, color="#555")
        ax.plot(modes["peaks"], np.interp(modes["peaks"], modes["freqs"], modes["spec"]), "rv", ms=5, label="measured peaks")
        f_ax, w = room_modes(L, config.MODE_FMAX)
        for f_ in f_ax[w == 1.0]:
            ax.axvline(f_, color="#1f4e9a", alpha=0.35, lw=1)
        ax.plot([], [], color="#1f4e9a", label="axial modes of estimate")
        ax.set_xlim(config.MODE_FMIN - 5, config.MODE_FMAX)
        ax.legend(fontsize=8)
    else:
        ax.text(0.5, 0.5, "no impulsive recordings -> no mode analysis", ha="center", transform=ax.transAxes)
    ax.set_xlabel("frequency (Hz)"); ax.set_ylabel("whitened level (dB)")
    ax.set_title("Low-frequency spectrum of clap tails" + ("" if settings.use_modes else " (not used in fit)"))
    ax.grid(alpha=0.3)

    ax = fig.add_subplot(2, 3, 5)
    for i, label in enumerate(["length", "width", "height"]):
        ax.hist(samples[:, i], bins=60, alpha=0.5, label=f"{label}  {np.median(samples[:, i]):.2f} m")
    if flutter:
        for d, s in flutter["candidates"]:
            ax.axvline(d, color="k", ls=":", alpha=min(1, 0.3 + 0.2 * s))
        ax.plot([], [], "k:", label="echo-periodicity distances")
    ax.set_xlabel("metres"); ax.set_title("Dimension uncertainty (MCMC)"); ax.legend(fontsize=8)

    ax = fig.add_subplot(2, 3, 6)
    colors = ["#2f6fd6" if a.side > 0 else "#e15759" if a.side < 0 else "#aaaaaa" for a in analyses]
    ax.barh([a.name for a in analyses], [-(a.ild_db or 0.0) for a in analyses], color=colors)
    ax.axvline(0, color="k", lw=0.8)
    for v in (-config.SIDE_MIN_DB, config.SIDE_MIN_DB):
        ax.axvline(v, color="k", ls=":", lw=0.8)
    ax.invert_yaxis()
    ax.set_xlabel("right minus left level at onset (dB)")
    ax.set_title("Which side of the phone the sound came from\n(<- left-channel end | right-channel end ->, grey = uncertain)", fontsize=10)

    fig.text(0.01, 0.005, "\n".join(notes), fontsize=9, family="monospace", va="bottom")
    fig.tight_layout(rect=(0, text_h / (11 + text_h) + 0.01, 1, 0.97))
    path = outdir / "report.png"
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def summary_text(notes, analyses, truth_lines, calibration, truth_file, files):
    lines = ["ROOM RECONSTRUCTION", "=" * 60, *notes, "",
             "Per recording (side: stereo level difference at the onset; distance from DRR):"]
    side_word = {1: "right-channel end", -1: "left-channel end", 0: "uncertain"}
    for a in analyses:
        dd = f"{a.distance_m:4.1f} m" if a.distance_m else " n/a"
        flag = "" if a.distance_m is None or a.distance_reliable else (
            f"  LOW CONFIDENCE: no distinct direct sound ({a.direct_prominence_db:.0f} dB above reverb, "
            f"need {config.DIRECT_MIN_DB:.0f})")
        lines.append(f"  {a.name:>8} ({a.kind}): side {side_word[a.side]:<17} ({a.ild_db:+.1f} dB)  distance {dd}{flag}")
        if a.doa_az_deg is not None:
            lines.append(f"           spatial audio: azimuth {a.doa_az_deg:+.0f} deg, elevation {a.doa_el_deg:+.0f} deg "
                         f"(phone frame, strength {a.doa_strength:.2f})")
    if truth_lines:
        same = calibration and calibration.get("mode", "room") == "room"
        lines += ["", "GROUND TRUTH COMPARISON" + (" (room priors copied from this same room - not an independent test)" if same else ""),
                  *truth_lines]
    else:
        lines += ["", f"(no ground truth in {truth_file} - fill it in to get an accuracy check)"]
    lines += [""] + [f"{k:<11} {v}" for k, v in files.items()]
    return "\n".join(lines)
