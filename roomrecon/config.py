"""Paths, constants and the (calibratable) model priors."""
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
VIDEO_DIR = DATA_DIR / "videos"
AUDIO_DIR = DATA_DIR / "audios"
SPATIAL_DIR = DATA_DIR / "spatial"            # <name>_foa.wav from tools/decode_spatial_audio.swift
TRUTH_FILE = DATA_DIR / "ground_truth" / "room_coordinates.txt"
CALIBRATION_FILE = ROOT / "config" / "calibration.json"
OUTPUT_DIR = ROOT / "output"
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

AUDIO_EXTS = {".wav"}
VIDEO_EXTS = {".mov", ".mp4", ".m4a", ".m4v"}

C = 343.0                     # speed of sound, m/s (~20 C)
BANDS = [125, 250, 500, 1000, 2000, 4000, 8000]
MID_BANDS = [500, 1000, 2000]
GUARD_S = 0.30                # ignore start/stop taps of the phone at the file edges
IMPULSIVE_MAX_S = 0.15        # excitations shorter than this count as impulsive (claps)
MODE_FMIN, MODE_FMAX = 35.0, 200.0
MAX_MODE_PEAKS = 20
FLUTTER_LAG_S = (0.006, 0.090)  # 1 m .. 15 m between parallel surfaces
BOUNDS = [(1.5, 25.0), (1.5, 25.0), (2.0, 8.0)]   # length, width, height search range (m)

# Stereo side: the iPhone stereo track behaves like a coincident virtual mic pair (no usable time
# difference), so direction shows up as a level difference between the channels right after the onset.
# Only the sign is reliable: which end of the phone's left-right axis the sound came from.
SIDE_WINDOW_S = (-0.0005, 0.010)
SIDE_MIN_DB = 1.5             # smaller level differences are reported as "uncertain"
DIRECT_MIN_DB = 10.0          # direct sound must stand this far above the early reverb for a DRR distance

# Calibrated same-room priors are tighter than the defaults but still let the audio move the answer.
CALIBRATED_SIGMA = {"length": 0.4, "width": 0.4, "height": 0.15, "absorption": 0.4}


@dataclass
class ModelSettings:
    """Priors are log-normal (median, sigma). Deliberately weak; a calibration can override them."""
    prior_height: tuple = (2.8, 0.25)
    prior_length: tuple = (4.5, 0.6)
    prior_width: tuple = (4.5, 0.6)
    prior_absorption: tuple = (0.12, 0.6)
    distance_scale: float = 1.0   # multiplies the DRR-based source distance
    # Low-frequency peaks in phone recordings are the same in the silence before the claps (device /
    # background noise, not room modes) and fit a measured room worse than random rooms do: off by default.
    use_modes: bool = False


settings = ModelSettings()


def apply_calibration(cal: dict) -> None:
    settings.prior_length = tuple(cal["prior_length"])
    settings.prior_width = tuple(cal["prior_width"])
    settings.prior_height = tuple(cal["prior_height"])
    settings.prior_absorption = tuple(cal["prior_absorption"])
    settings.distance_scale = float(cal["distance_scale"])
