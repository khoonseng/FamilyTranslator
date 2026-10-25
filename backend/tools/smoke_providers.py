"""Calls every provider adapter once against the real services, with credentials from
backend/.env (local only; prints to this terminal, never to logs).

Run: cd backend && uv run python tools/smoke_providers.py <16 kHz mono WAV of Mandarin speech>
e.g. a guide chunk from ../bakeoff/out/chunks/guide/ (local only, never committed).
"""

import asyncio
import sys
import wave
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.providers import build  # noqa: E402
from app.providers.stt import RATE  # noqa: E402
from app.providers.translator import Translator  # noqa: E402

SENTENCE = "洪崖洞晚上七点半以后开灯，那个时候人特别多，大家一定要跟紧我，不要走散了。"


def read_pcm(path: str) -> bytes:
    with wave.open(path, "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (RATE, 1, 2):
            raise SystemExit("need a 16 kHz mono 16-bit WAV")
        return w.readframes(w.getnframes())


async def stream_at_speaking_pace(p, pcm: bytes) -> None:
    languages = config.load()["stt"]["google"]["guide_languages"]
    stream = p.stt.open(languages)
    frame = RATE * 2 // 10  # 100 ms
    start = perf_counter()
    for i in range(0, len(pcm), frame):
        stream.send(pcm[i : i + frame])
        await asyncio.sleep(max(0.0, start + (i + frame) / (2 * RATE) - perf_counter()))
    stream.send(bytes(RATE * 2))  # 1 s of silence, as the hub's VAD lets through
    speech_end = perf_counter()
    await stream.close(timeout_s=10)
    finals = []
    while (final := stream.finals.get_nowait()) is not None:
        finals.append(final)
    error = type(stream.error).__name__ if stream.error else None
    print(f"chirp 3 stream: {len(finals)} finals, error={error}")
    if stream.error:
        print(f"  {stream.error}")
    for f in finals:
        print(f"  ends at {f.end_s:.2f}s [{f.language}] {f.text}")
    print(f"  closed {perf_counter() - speech_end:.2f}s after the speech ended")


async def main() -> None:
    p = build()
    t = p.translator

    for label, translator in (
        ("gemini → qwen → cloud", t),
        ("qwen only", Translator(t.models[1:], t.fallback, t.yue_deadline_s, t.timeout_s)),
        ("cloud translation only", Translator([], t.fallback, t.yue_deadline_s, t.timeout_s)),
    ):
        result = await translator.translate(SENTENCE, [])
        attempts = [(a.provider, a.outcome) for a in result.attempts]
        print(f"{label}: {result.provider} in {result.yue_s:.2f}s, passed over {attempts}")
        print(f"  yue: {result.yue}\n  en:  {await result.en}")

    tts = p.tts
    for voice in tts.voices:
        start = perf_counter()
        audio = await tts._synthesize("洪崖洞夜晚七點半之後會開燈。", voice)
        print(f"tts {voice}: {len(audio)} bytes in {perf_counter() - start:.2f}s")

    if len(sys.argv) > 1:
        pcm = read_pcm(sys.argv[1])
        await stream_at_speaking_pace(p, pcm)
        start = perf_counter()
        text = await p.transcribe.transcribe(pcm)
        print(f"gpt-transcribe in {perf_counter() - start:.2f}s: {text}")


if __name__ == "__main__":
    asyncio.run(main())
