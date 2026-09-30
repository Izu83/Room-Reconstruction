"""Reading recordings: videos, WAV files and optional Spatial Audio (ambisonics) side files.

iPhone "Spatial Audio" videos carry two audio tracks:
  * AAC stereo (48 kHz), decodable anywhere
  * APAC (Apple Positional Audio Codec) first-order ambisonics, decodable only by Apple frameworks
    (see tools/decode_spatial_audio.swift). FFmpeg's "apac" decoder is an unrelated codec.
"""
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from . import config


@dataclass
class Recording:
    name: str
    path: Path
    sr: int
    stereo: np.ndarray              # (2, n)
    foa: np.ndarray | None = None   # (4, n) first-order ambisonics, ACN order W Y Z X, SN3D
    foa_sr: int | None = None
    mono: np.ndarray = field(init=False)

    def __post_init__(self):
        self.mono = self.stereo.mean(axis=0)


def decode_video_audio(src: Path) -> tuple[int, np.ndarray]:
    """Decode the first decodable audio track (the stereo one). Returns (sr, float32 (channels, n))."""
    import av
    with av.open(str(src)) as container:
        # the APAC spatial track has no codec context in FFmpeg and is skipped here
        stream = next(s for s in container.streams.audio if s.codec_context is not None)
        sr = stream.codec_context.sample_rate
        chunks = [frame.to_ndarray() for frame in container.decode(stream)]
    return sr, np.concatenate(chunks, axis=1).astype(np.float32, copy=False)


def read_wav(path: Path) -> tuple[int, np.ndarray]:
    sr, audio = wavfile.read(str(path))
    if audio.dtype.kind == "i":
        audio = audio / float(np.iinfo(audio.dtype).max)
    return sr, np.atleast_2d(audio.T if audio.ndim == 2 else audio).astype(np.float64)


def load_recording(path: Path) -> Recording:
    if path.suffix.lower() in config.VIDEO_EXTS:
        sr, audio = decode_video_audio(path)
        audio = audio.astype(np.float64)
    else:
        sr, audio = read_wav(path)
    name = path.stem[:-4] if path.stem.endswith("_foa") else path.stem
    foa, foa_sr = None, None
    if audio.shape[0] == 4:                       # an ambisonics file given directly
        foa, foa_sr = audio, sr
        audio = np.vstack([audio[0], audio[0]])
    else:
        side = config.SPATIAL_DIR / f"{name}_foa.wav"
        if side.exists():
            foa_sr, foa = read_wav(side)
            if foa.shape[0] != 4:
                foa, foa_sr = None, None
    if audio.shape[0] == 1:
        audio = np.vstack([audio, audio])
    return Recording(name, path, sr, audio[:2], foa, foa_sr)


def extract_videos(video_dir: Path = config.VIDEO_DIR, audio_dir: Path = config.AUDIO_DIR) -> list[Path]:
    """Write the stereo track of every video in video_dir to audio_dir/<name>.wav."""
    audio_dir.mkdir(parents=True, exist_ok=True)
    videos = sorted(p for p in video_dir.iterdir() if p.suffix.lower() in config.VIDEO_EXTS)
    written = []
    for src in videos:
        sr, audio = decode_video_audio(src)
        dst = audio_dir / (src.stem + ".wav")
        wavfile.write(str(dst), sr, audio.T)
        print(f"{src.name:>12} -> {dst.relative_to(config.ROOT)}  ({audio.shape[0]} ch, {sr} Hz, {audio.shape[1] / sr:.2f} s)")
        written.append(dst)
    return written


def discover_inputs(inputs: list[str]) -> list[Path]:
    if inputs:
        paths = []
        for p in map(Path, inputs):
            if p.is_dir():
                paths += sorted(q for q in p.iterdir() if q.suffix.lower() in config.AUDIO_EXTS | config.VIDEO_EXTS)
            else:
                paths.append(p)
        return paths
    audios = sorted(config.AUDIO_DIR.glob("*.wav")) if config.AUDIO_DIR.exists() else []
    if audios:
        return audios
    if not config.VIDEO_DIR.exists():
        return []
    return sorted(q for q in config.VIDEO_DIR.iterdir() if q.suffix.lower() in config.VIDEO_EXTS)
