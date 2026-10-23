import numpy as np

from lib import audio

RATE = audio.RATE


def tone(seconds: float, amplitude: int = 8000) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    return (amplitude * np.sin(2 * np.pi * 220 * t)).astype(np.int16)


def quiet(seconds: float) -> np.ndarray:
    rng = np.random.default_rng(0)
    return rng.integers(-30, 30, int(seconds * RATE)).astype(np.int16)


def test_splits_at_long_pause_only():
    pcm = np.concatenate([quiet(0.5), tone(2), quiet(0.3), tone(1), quiet(1.2), tone(1.5)])
    chunks = audio.split_at_pauses(pcm)
    # the 0.3 s gap is a breath, not a pause; the 1.2 s gap ends the first chunk
    assert len(chunks) == 2
    first_s = (chunks[0][1] - chunks[0][0]) / RATE
    assert 3.2 < first_s < 3.8


def test_caps_long_speech_at_max_chunk():
    pcm = np.concatenate([tone(40), quiet(1)])
    chunks = audio.split_at_pauses(pcm, max_chunk_s=15)
    assert len(chunks) == 3
    for start, end in chunks:
        assert (end - start) / RATE <= 15 + 2 * 0.15 + 0.01  # cap plus padding


def test_drops_tiny_blips():
    pcm = np.concatenate([quiet(1), tone(0.1), quiet(1), tone(1), quiet(1)])
    assert len(audio.split_at_pauses(pcm)) == 1


def test_wav_roundtrip(tmp_path):
    pcm = tone(0.5)
    path = tmp_path / "x.wav"
    audio.write_wav(path, pcm)
    assert np.array_equal(audio.decode(path), pcm)


def test_normalize_levels_quiet_speech_without_clipping():
    quiet_speech = tone(2, amplitude=900)  # about -31 dBFS
    out = audio.normalize(quiet_speech, target_dbfs=-20)
    rms_db = 20 * np.log10(np.sqrt(np.mean(out.astype(float) ** 2)) / 32768)
    assert abs(rms_db - (-20)) < 0.5
    assert np.abs(out).max() <= 32767


def test_normalize_caps_gain_and_leaves_silence():
    assert not audio.normalize(np.zeros(1600, np.int16)).any()
    hiss = quiet(1)  # ~ -70 dBFS: capped at +20 dB, so it stays quiet
    assert np.abs(audio.normalize(hiss)).max() < 400
