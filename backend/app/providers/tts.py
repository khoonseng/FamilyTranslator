"""Google Text-to-Speech: Cantonese MP3, one non-streaming request per sentence (CLAUDE.md
"Stack"). Voices in config order: Despina, then the older Standard-A (hard rule 6). Normal
speed, never sped up (hard rule 11)."""

from time import perf_counter

from google.api_core.client_options import ClientOptions
from google.cloud import texttospeech as tts

from app.providers.base import Attempt, Speech, SpeechFailed, outcome_of


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

    async def speak(self, text: str) -> Speech:
        attempts: list[Attempt] = []
        for voice in self.voices:
            t0 = perf_counter()
            try:
                audio = await self._synthesize(text, voice)
                if not audio:
                    raise ValueError("empty audio")
            except Exception as exc:  # noqa: BLE001 - any failure moves to the next voice
                attempts.append(Attempt(voice, outcome_of(exc), round(perf_counter() - t0, 3)))
                continue
            return Speech(audio, voice, round(perf_counter() - t0, 3), attempts)
        raise SpeechFailed(attempts)
