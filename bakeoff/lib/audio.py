"""Audio prep that mimics the hub: 16 kHz mono 16-bit PCM, chunks ending at pauses, 15 s cap.

The hub uses Silero VAD in the browser; here a simple energy threshold stands in for it,
which is close enough to cut guide videos and voice memos into hub-like chunks."""

import io
import wave
from pathlib import Path
from typing import BinaryIO

import av
import numpy as np

RATE = 16_000


def decode(path: str | Path | BinaryIO, rate: int = RATE) -> np.ndarray:
    """Decode any audio/video file (m4a, mp4, mp3, wav...) to mono int16 PCM at `rate`.
    `path` may also be an open file, e.g. io.BytesIO(mp3_bytes)."""
    resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)
    parts = []
    with av.open(str(path) if isinstance(path, str | Path) else path) as container:
        stream = container.streams.audio[0]
        for frame in container.decode(stream):
            parts.extend(f.to_ndarray().reshape(-1) for f in resampler.resample(frame))
        parts.extend(f.to_ndarray().reshape(-1) for f in resampler.resample(None))
    return np.concatenate(parts).astype(np.int16) if parts else np.zeros(0, np.int16)


def frame_db(pcm: np.ndarray, frame_len: int) -> np.ndarray:
    """Loudness of each frame in dBFS."""
    n = len(pcm) // frame_len
    frames = pcm[: n * frame_len].astype(np.float64).reshape(n, frame_len) / 32768.0
    rms = np.sqrt(np.mean(frames**2, axis=1))
    return 20 * np.log10(rms + 1e-10)


def split_at_pauses(
    pcm: np.ndarray,
    rate: int = RATE,
    min_pause_s: float = 0.7,
    max_chunk_s: float = 15.0,
    min_speech_s: float = 0.3,
    frame_ms: int = 30,
    pad_s: float = 0.15,
    threshold_db: float | None = None,
) -> list[tuple[int, int]]:
    """Return (start, end) sample ranges of speech chunks.

    A chunk ends after `min_pause_s` of quiet, or is cut at `max_chunk_s` like the hub's cap.
    The speech threshold defaults to 10 dB above the quietest fifth of the recording, but never
    more than 15 dB below its loud end, so a recording that is nearly all speech still splits."""
    frame_len = rate * frame_ms // 1000
    db = frame_db(pcm, frame_len)
    if len(db) == 0:
        return []
    if threshold_db is None:
        noise_based = float(np.percentile(db, 20)) + 10.0
        loud_based = float(np.percentile(db, 95)) - 15.0
        threshold_db = max(min(noise_based, loud_based), -60.0)
    speech = db > threshold_db

    pause_frames = round(min_pause_s * 1000 / frame_ms)
    max_frames = round(max_chunk_s * 1000 / frame_ms)
    pad = round(pad_s * rate)

    chunks, start, last_speech = [], None, None
    for i, is_speech in enumerate(speech):
        if start is None:
            if is_speech:
                start, last_speech = i, i
            continue
        if is_speech:
            last_speech = i
        if i - last_speech >= pause_frames:
            chunks.append((start, last_speech + 1))
            start = None
        elif i + 1 - start >= max_frames:
            chunks.append((start, i + 1))
            start = None
    if start is not None:
        chunks.append((start, last_speech + 1))

    min_frames = round(min_speech_s * 1000 / frame_ms)
    return [
        (max(0, s * frame_len - pad), min(len(pcm), e * frame_len + pad))
        for s, e in chunks
        if e - s >= min_frames
    ]


def normalize(pcm: np.ndarray, target_dbfs: float = -20.0, max_gain_db: float = 20.0) -> np.ndarray:
    """Scale speech to a steady loudness (RMS in dBFS), without clipping. The gain is capped so
    near-silence isn't blown up into noise.

    Tested as a fix for Chirp 3 streaming dropping speech (2026-10-23) and rejected: it didn't
    stop the drop and made transcripts worse. Kept for the option in config.yaml."""
    samples = pcm.astype(np.float64)
    rms = np.sqrt(np.mean(samples**2)) if len(samples) else 0.0
    if rms == 0:
        return pcm.astype(np.int16)
    gain_db = min(max_gain_db, target_dbfs - 20 * np.log10(rms / 32768.0))
    peak = np.abs(samples).max()
    gain = min(10 ** (gain_db / 20), 32767 / peak)  # never clip
    return np.round(samples * gain).astype(np.int16)


class Mp3Encoder:
    """Continuous MP3 encoder: feed PCM in pieces, get MP3 frames back. One encoder per stream,
    so a never-ending stream ("radio mode") stays one valid MP3."""

    def __init__(self, rate: int, bit_rate: int = 48_000):
        self.rate = rate
        self.ctx = av.CodecContext.create("libmp3lame", "w")
        self.ctx.sample_rate = rate
        self.ctx.layout = "mono"
        self.ctx.format = "s16p"
        self.ctx.bit_rate = bit_rate
        self.ctx.open()

    def encode(self, pcm: np.ndarray) -> bytes:
        frame = av.AudioFrame.from_ndarray(
            pcm.astype(np.int16).reshape(1, -1), format="s16p", layout="mono"
        )
        frame.sample_rate = self.rate
        return b"".join(bytes(p) for p in self.ctx.encode(frame))

    def flush(self) -> bytes:
        return b"".join(bytes(p) for p in self.ctx.encode(None))


def mp3_bytes(pcm: np.ndarray, rate: int) -> bytes:
    encoder = Mp3Encoder(rate)
    return encoder.encode(pcm) + encoder.flush()


def wav_bytes(pcm: np.ndarray, rate: int = RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.astype(np.int16).tobytes())
    return buf.getvalue()


def write_wav(path: str | Path, pcm: np.ndarray, rate: int = RATE) -> None:
    Path(path).write_bytes(wav_bytes(pcm, rate))


def duration_s(pcm: np.ndarray, rate: int = RATE) -> float:
    return len(pcm) / rate
