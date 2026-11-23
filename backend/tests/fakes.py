"""Fake providers for pipeline tests: no network, controllable timing."""

import asyncio
from dataclasses import dataclass

from app.providers.base import Attempt, Speech, SpeechFailed, SttFinal, Translation


class FakeStream:
    def __init__(self):
        self.finals: asyncio.Queue = asyncio.Queue()
        self.error = None
        self.closed = False
        self.audio_s = 0.0
        self.age_s = 0.0
        self.sent = b""
        self.auto_end = True  # False: finals may still arrive after close(), until end()

    def opened_age_s(self) -> float:
        return self.age_s

    def send(self, pcm: bytes) -> None:
        self.sent += pcm
        self.audio_s += len(pcm) / 32_000

    def final(self, text: str, end_s: float | None = None) -> None:
        """Test helper: Chirp 3 returns a final transcript."""
        self.finals.put_nowait(SttFinal(text, self.audio_s if end_s is None else end_s))

    async def close(self) -> None:
        if not self.closed:
            self.closed = True
            if self.auto_end:
                self.end()

    def end(self) -> None:
        self.finals.put_nowait(None)


class FakeStt:
    def __init__(self):
        self.streams: list[FakeStream] = []

    def open(self, languages):
        stream = FakeStream()
        stream.languages = languages
        self.streams.append(stream)
        return stream


class FakeTranslator:
    """Translates to "粵:<text>"; `delays` maps text -> seconds; `fail` texts fail outright."""

    def __init__(self, delays=None, fail=()):
        self.delays, self.fail = delays or {}, set(fail)
        self.calls: list[tuple[str, list[str]]] = []
        self.directions: list[str] = []
        self.warmed = False

    async def warm_up(self):
        self.warmed = True

    async def translate(self, text, context, direction="guide"):
        """Guide → family: "粵:<text>", then "en:<text>"; a reply (family): "普:<text>" (the
        Mandarin for the guide), then "other:<text>"."""
        from app.providers.base import TranslationFailed

        self.calls.append((text, context))
        self.directions.append(direction)
        await asyncio.sleep(self.delays.get(text, 0))
        if text in self.fail:
            raise TranslationFailed([Attempt("gemini", "429", 0.1)])
        speech, other = ("普", "other") if direction == "family" else ("粵", "en")

        async def rest():
            return f"{other}:{text}"

        return Translation(f"{speech}:{text}", asyncio.ensure_future(rest()), "gemini", 0.1)


class FakeTts:
    """Despina, unless the text is in `fail` (every voice fails) or `fallback` (Despina refuses
    it and Standard-A speaks it, like a sentence too long for Despina)."""

    def __init__(self, fail=(), fallback=(), voice="yue-HK-Chirp3-HD-Despina"):
        self.fail, self.fallback, self.voice = set(fail), set(fallback), voice

    async def speak(self, text):
        if text in self.fail:
            raise SpeechFailed([Attempt(self.voice, "error", 0.1)])
        if text in self.fallback:
            refused = [Attempt(self.voice, "rejected", 0.1)]
            return Speech(f"mp3:{text}".encode(), "yue-HK-Standard-A", 0.1, refused)
        return Speech(f"mp3:{text}".encode(), self.voice, 0.1)


class FakeTranscribe:
    """gpt-transcribe: returns `text` (or raises `error`) and records how much audio it got."""

    def __init__(self, text="", error=None):
        self.text, self.error = text, error
        self.calls: list[int] = []  # bytes of PCM per call

    async def transcribe(self, pcm: bytes) -> str:
        self.calls.append(len(pcm))
        if self.error:
            raise self.error
        return self.text


@dataclass
class FakeProviders:
    translator: FakeTranslator
    family_tts: FakeTts
    stt: FakeStt
    transcribe: FakeTranscribe
    guide_tts: "FakeTts"


def fake_providers(**kwargs) -> FakeProviders:
    return FakeProviders(
        kwargs.get("translator", FakeTranslator()),
        kwargs.get("family_tts", FakeTts()),
        kwargs.get("stt", FakeStt()),
        kwargs.get("transcribe", FakeTranscribe()),
        kwargs.get("guide_tts", FakeTts(voice="cmn-CN-Chirp3-HD-Kore")),
    )
