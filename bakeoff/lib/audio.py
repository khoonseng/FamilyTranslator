"""Audio prep that mimics the hub: 16 kHz mono 16-bit PCM, chunks ending at pauses, 15 s cap.

The hub uses Silero VAD in the browser; here a simple energy threshold stands in for it,
which is close enough to cut guide videos and voice memos into hub-like chunks."""

import io
import wave
from pathlib import Path

import av
import numpy as np

RATE = 16_000


def decode(path: str | Path, rate: int = RATE) -> np.ndarray:
    """Decode any audio/video file (m4a, mp4, mp3, wav...) to mono int16 PCM at `rate`."""
    resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)
    parts = []
    with av.open(str(path)) as container:
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
