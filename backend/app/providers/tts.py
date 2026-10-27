"""Google Text-to-Speech: Cantonese MP3, one non-streaming request per sentence (CLAUDE.md
"Stack"). Voices in config order: Despina, then the older Standard-A (hard rule 6). Normal
speed, never sped up (hard rule 11).

Despina refuses a single sentence that is too long (400 "This request contains sentences that
are too long"; an 85-character sentence joined only by commas, 27 Oct). Then the sentence is
split at the comma nearest its middle, again if need be, and Despina speaks the pieces at the
same time; their MP3s are joined into one clip (owner decision 2026-10-27). The words are
exactly the displayed `yue` (hard rule 5), and Google's MP3s are plain frames with no tags or
length header, so the joined clip plays as one. Only if a piece can't be split further does
the sentence go to the next voice."""

import asyncio
from time import perf_counter

from google.api_core.client_options import ClientOptions
from google.cloud import texttospeech as tts

from app.providers.base import Attempt, Speech, SpeechFailed, outcome_of

SPLIT_AT = "，；：、,;:"  # where a long sentence may be cut; the mark stays with the first piece
MAX_SPLITS = 3  # halvings deep: at most 8 pieces


def too_long(exc: BaseException) -> bool:
    return outcome_of(exc) == "rejected" and "too long" in str(exc)


def split_in_two(text: str) -> tuple[str, str] | None:
    """At the punctuation mark nearest the middle; None if there is none to cut at."""
    marks = [i for i in range(1, len(text) - 1) if text[i] in SPLIT_AT]
    if not marks:
        return None
    middle = len(text) / 2
    cut = min(marks, key=lambda i: abs(i + 1 - middle)) + 1
    return text[:cut], text[cut:]


class GoogleTts:
    def __init__(self, cfg: dict):
        self.endpoint = cfg["endpoint"]
        self.language = cfg["language"]
        self.voices = cfg["voices"]
        self.speaking_rate = cfg.get("speaking_rate", 1.0)
        self.timeout_s = cfg.get("timeout_s", 8)
        self._client = None  # created on first use, inside the event loop

    async def _synthesize(self, text: str, voice: str) -> bytes:
        if self._client is None:
            self._client = tts.TextToSpeechAsyncClient(
                client_options=ClientOptions(api_endpoint=self.endpoint)
            )
        response = await self._client.synthesize_speech(
            input=tts.SynthesisInput(text=text),
            voice=tts.VoiceSelectionParams(language_code=self.language, name=voice),
            audio_config=tts.AudioConfig(
                audio_encoding=tts.AudioEncoding.MP3, speaking_rate=self.speaking_rate
            ),
            timeout=self.timeout_s,
        )
        return response.audio_content

    async def _pieces(self, text: str, voice: str, depth: int = 0) -> tuple[bytes, int]:
        """The sentence's MP3 and how many pieces it took (1 unless it was too long)."""
        try:
            return await self._synthesize(text, voice), 1
        except Exception as exc:
            halves = split_in_two(text) if depth < MAX_SPLITS and too_long(exc) else None
            if halves is None:
                raise
        first, second = await asyncio.gather(*(self._pieces(h, voice, depth + 1) for h in halves))
        return first[0] + second[0], first[1] + second[1]

    async def speak(self, text: str) -> Speech:
        attempts: list[Attempt] = []
        for voice in self.voices:
            t0 = perf_counter()
            try:
                audio, pieces = await self._pieces(text, voice)
                if not audio:
                    raise ValueError("empty audio")
            except Exception as exc:  # noqa: BLE001 - any failure moves to the next voice
                attempts.append(Attempt(voice, outcome_of(exc), round(perf_counter() - t0, 3)))
                continue
            return Speech(audio, voice, round(perf_counter() - t0, 3), attempts, pieces)
        raise SpeechFailed(attempts)
