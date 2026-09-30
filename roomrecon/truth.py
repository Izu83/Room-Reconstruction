"""Ground-truth file: parsing and comparison with the estimate."""
import re
from pathlib import Path

import numpy as np

NUM = r"-?\d+(?:[.,]\d+)?"


def parse_truth(path: Path):
    """Read ground truth. Two layouts are accepted (numbers may use a decimal comma):

        Room:              room: 6.14 2.40 12.25
        X 6,14             phone: 4.2 1.65 2.43
        Y 2,40             video 1: 7 0.7 1.17
        Z 12,25            phone_right: 0 0 1
    Keys: room, phone (or mic), phone_right (direction of the phone's right stereo channel), and one
    source per recording name or "video N" (matches clapN / yellN). Returns {key: [x, y, z]}.
    """
    if not path or not path.exists() or path.stat().st_size == 0:
        return None
    truth, section = {}, None
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        head = re.match(r"^([A-Za-z][\w ]*?)\s*[:=]\s*(.*)$", line)
        axis = re.match(r"^([XYZxyz])\d*\s*[:=]?\s*(" + NUM + r")\s*$", line)
        if head and not axis:
            section = head.group(1).strip().lower()
            nums = [float(v.replace(",", ".")) for v in re.findall(NUM, head.group(2))]
            truth[section] = nums[:3] if len(nums) >= 3 else [None, None, None]
        elif axis and section:
            truth[section]["xyz".index(axis.group(1).lower())] = float(axis.group(2).replace(",", "."))
    truth = {k: v for k, v in truth.items() if v and all(x is not None for x in v)}
    return truth or None


def truth_source(truth, name):
    if name.lower() in truth:
        return truth[name.lower()]
    num = re.search(r"(\d+)$", name)
    return truth.get(f"video {num.group(1)}") if num else None


def truth_room(truth, up_axis):
    """(length, width, height) of the true room, horizontal dimensions sorted longest first."""
    room = truth.get("room")
    if not room:
        return None
    up = "xyz".index(up_axis)
    return np.array(sorted((room[i] for i in range(3) if i != up), reverse=True) + [room[up]])


def truth_distance(truth, name):
    src, phone = truth_source(truth, name), truth.get("phone") or truth.get("mic")
    if src and phone:
        return float(np.linalg.norm(np.array(src) - np.array(phone)))
    return None


def compare_truth(truth, L, analyses, up_axis):
    out = []
    room = truth.get("room")
    true_L = truth_room(truth, up_axis)
    if true_L is not None:
        tv, ev = float(np.prod(true_L)), float(np.prod(L))
        errs = [abs(e - t) / t * 100 for e, t in zip(L, true_L)]
        out.append(f"Room   true {true_L[0]:.2f} x {true_L[1]:.2f} x {true_L[2]:.2f} m (V={tv:.0f} m3)")
        out.append(f"       est  {L[0]:.2f} x {L[1]:.2f} x {L[2]:.2f} m (V={ev:.0f} m3)")
        out.append(f"       errors: length {errs[0]:.0f}%  width {errs[1]:.0f}%  height {errs[2]:.0f}%  volume {abs(ev - tv) / tv * 100:.0f}%")
    phone = truth.get("phone") or truth.get("mic")
    right = truth.get("phone_right")
    agree = total = 0
    word = {1: "right end", -1: "left end", 0: "uncertain"}
    for a in analyses:
        src = truth_source(truth, a.name)
        if not (src and phone):
            continue
        d = float(np.linalg.norm(np.array(src) - np.array(phone)))
        est = f"{a.distance_m:.2f} m" if a.distance_m else "n/a (not a clap)"
        line = f"{a.name:>8}: true source distance {d:.2f} m, estimated {est}"
        if right:
            true_side = 1 if np.dot(np.array(src) - np.array(phone), np.array(right)) > 0 else -1
            line += f" | side: true {word[true_side]}, heard {word[a.side]} ({a.ild_db:+.1f} dB)"
            if a.side:
                total += 1
                agree += a.side == true_side
        out.append(line)
    if total:
        out.append(f"Side (stereo level difference): {agree}/{total} correct")
    if room:
        for k, v in truth.items():
            if k not in ("room", "phone_right") and any(not 0 <= v[i] <= room[i] for i in range(3)):
                out.append(f"  note: '{k}' {v} lies outside the room box {room} - check axes in the truth file")
    return out
