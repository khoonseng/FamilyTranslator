"""Google Text-to-Speech adapter: Chirp 3 HD and older voices, one non-streaming request each."""

from dataclasses import dataclass
from time import perf_counter

from google.api_core.client_options import ClientOptions
from google.cloud import texttospeech as tts


@dataclass
class Voice:
    name: str
    languages: list[str]
    gender: str
    sample_rate_hz: int

    @property
    def is_chirp3_hd(self) -> bool:
        return "Chirp3-HD" in self.name


@dataclass
class TtsResult:
    audio: bytes
    latency_s: float


class GoogleTts:
    def __init__(self, cfg: dict):
        self.client = tts.TextToSpeechClient(
            client_options=ClientOptions(api_endpoint=cfg["endpoint"])
        )

    def voices(self, language_code: str) -> list[Voice]:
        response = self.client.list_voices(language_code=language_code)
        return sorted(
            (
                Voice(
                    name=v.name,
                    languages=list(v.language_codes),
                    gender=tts.SsmlVoiceGender(v.ssml_gender).name,
                    sample_rate_hz=v.natural_sample_rate_hertz,
                )
                for v in response.voices
            ),
            key=lambda v: v.name,
        )

    def synthesize(
        self,
        text: str,
        voice: str,
        language_code: str,
        encoding: str = "MP3",
        speaking_rate: float = 1.0,
        sample_rate_hz: int | None = None,
    ) -> TtsResult:
        """encoding: MP3 for listener clips; LINEAR16 (WAV) when the audio feeds STT."""
        audio_config = tts.AudioConfig(
            audio_encoding=tts.AudioEncoding[encoding], speaking_rate=speaking_rate
        )
        if sample_rate_hz:
            audio_config.sample_rate_hertz = sample_rate_hz
        start = perf_counter()
        response = self.client.synthesize_speech(
            input=tts.SynthesisInput(text=text),
            voice=tts.VoiceSelectionParams(language_code=language_code, name=voice),
            audio_config=audio_config,
        )
        return TtsResult(audio=response.audio_content, latency_s=perf_counter() - start)
