"""Speech-to-text adapters (hard rule 9): Google Chirp 3 streaming, and OpenAI `gpt-transcribe`
for the safety net and fallback. Streaming only, never the batch endpoint (hard rule 14).

A ChirpStream is one streaming session: the pipeline opens one per hub segment, feeds it the
hub's PCM as it arrives (about real-time pace, as Google requires), and closes it when the
segment ends, which makes Chirp 3 return the final transcript at once (app/pipeline)."""

import asyncio
import io
import os
import wave
from time import monotonic

from google.api_core.client_options import ClientOptions
from google.cloud.speech_v2 import SpeechAsyncClient
from google.cloud.speech_v2.types import cloud_speech as cs
from openai import AsyncOpenAI

from app.providers.base import SttFinal

RATE = 16_000
MAX_MESSAGE_BYTES = 25_000  # Google's cap per streaming message

_SENSITIVITY = cs.StreamingRecognitionFeatures.EndpointingSensitivity
_ENDPOINTING = {
    "standard": _SENSITIVITY.ENDPOINTING_SENSITIVITY_STANDARD,
    "short": _SENSITIVITY.ENDPOINTING_SENSITIVITY_SHORT,
    "supershort": _SENSITIVITY.ENDPOINTING_SENSITIVITY_SUPERSHORT,
}


class ChirpStream:
    """Feed PCM with send(); final transcripts arrive on `finals`, then None when it ends."""

    def __init__(self, client: SpeechAsyncClient, first_request: cs.StreamingRecognizeRequest):
        self._client = client
        self._first = first_request
        self._audio: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.finals: asyncio.Queue[SttFinal | None] = asyncio.Queue()
        self.error: BaseException | None = None
        self.opened_at = monotonic()
        self.audio_s = 0.0  # audio sent so far
        self._closed = False
        self._task = asyncio.create_task(self._run())

    @property
    def closed(self) -> bool:
        return self._closed

    def opened_age_s(self) -> float:
        return monotonic() - self.opened_at

    def send(self, pcm: bytes) -> None:
        if self._closed:
            return
        for i in range(0, len(pcm), MAX_MESSAGE_BYTES):
            self._audio.put_nowait(pcm[i : i + MAX_MESSAGE_BYTES])
        self.audio_s += len(pcm) / (2 * RATE)

    async def close(self, timeout_s: float = 5.0) -> None:
        """No more audio; waits for the last finals."""
        if not self._closed:
            self._closed = True
            self._audio.put_nowait(None)
        try:
            await asyncio.wait_for(asyncio.shield(self._task), timeout_s)
        except TimeoutError:
            self._task.cancel()

    async def _requests(self):
        yield self._first
        while (pcm := await self._audio.get()) is not None:
            yield cs.StreamingRecognizeRequest(audio=pcm)

    async def _run(self) -> None:
        try:
            responses = await self._client.streaming_recognize(requests=self._requests())
            async for response in responses:
                for result in response.results:
                    if not result.is_final or not result.alternatives:
                        continue
                    text = result.alternatives[0].transcript.strip()
                    if text:
                        self.finals.put_nowait(
                            SttFinal(
                                text=text,
                                end_s=result.result_end_offset.total_seconds(),
                                language=result.language_code or "",
                            )
                        )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the pipeline falls back (hard rule 9)
            self.error = exc
        finally:
            self._closed = True
            self.finals.put_nowait(None)


class GoogleStreamingStt:
    def __init__(self, cfg: dict, project: str, phrases: list[str]):
        self.cfg = cfg
        self.recognizer = f"projects/{project}/locations/{cfg['location']}/recognizers/_"
        self.phrases = phrases
        self._client = None  # created on first use, inside the event loop

    def _first_request(self, languages: list[str]) -> cs.StreamingRecognizeRequest:
        config = cs.RecognitionConfig(
            model=self.cfg["model"],
            language_codes=languages,
            features=cs.RecognitionFeatures(enable_automatic_punctuation=True),
            explicit_decoding_config=cs.ExplicitDecodingConfig(
                encoding=cs.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=RATE,
                audio_channel_count=1,
            ),
        )
        if self.phrases:
            boost = self.cfg.get("phrase_boost", 10)
            phrase_set = cs.PhraseSet(
                phrases=[cs.PhraseSet.Phrase(value=p, boost=boost) for p in self.phrases]
            )
            config.adaptation = cs.SpeechAdaptation(
                phrase_sets=[cs.SpeechAdaptation.AdaptationPhraseSet(inline_phrase_set=phrase_set)]
            )
        return cs.StreamingRecognizeRequest(
            recognizer=self.recognizer,
            streaming_config=cs.StreamingRecognitionConfig(
                config=config,
                streaming_features=cs.StreamingRecognitionFeatures(
                    endpointing_sensitivity=_ENDPOINTING[self.cfg.get("endpointing", "standard")],
                ),
            ),
        )

    def open(self, languages: list[str]) -> ChirpStream:
        if self._client is None:
            self._client = SpeechAsyncClient(
                client_options=ClientOptions(api_endpoint=self.cfg["endpoint"])
            )
        return ChirpStream(self._client, self._first_request(languages))


def wav_bytes(pcm: bytes, rate: int = RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


class OpenAiTranscribe:
    """`gpt-transcribe` on a saved segment (hard rule 9). Guide mode carries Mandarin and
    Cantonese, so there is no language hint; the glossary goes in as a prompt."""

    name = "gpt-transcribe"

    def __init__(self, cfg: dict, phrases: list[str]):
        self.model = cfg["model"]
        self.prompt = "Places and dishes: " + ", ".join(phrases) if phrases else None
        self._client = AsyncOpenAI(
            api_key=os.environ.get("OPENAI_API_KEY") or "pending",
            timeout=cfg.get("timeout_s", 10),
            max_retries=0,
        )

    async def transcribe(self, pcm: bytes) -> str:
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is not set")
        kwargs = {"prompt": self.prompt} if self.prompt else {}
        response = await self._client.audio.transcriptions.create(
            model=self.model, file=("segment.wav", wav_bytes(pcm), "audio/wav"), **kwargs
        )
        return response.text.strip()
