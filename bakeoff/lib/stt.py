"""Speech-to-text adapters: Google Chirp 3 (sync Recognize and streaming) and OpenAI
transcription. Never the batch endpoint (hard rule 14)."""

import os
import time
from dataclasses import dataclass, field
from time import perf_counter

from google.api_core.client_options import ClientOptions
from google.cloud.speech_v2 import SpeechClient
from google.cloud.speech_v2.types import cloud_speech as cs
from openai import OpenAI


@dataclass
class SttResult:
    text: str
    latency_s: float
    # (text, language label) per recognition result; Chirp 3 only, empty for OpenAI.
    segments: list[tuple[str, str]] = field(default_factory=list)

    @property
    def languages(self) -> list[str]:
        return [lang for _, lang in self.segments]

    def labelled_cantonese(self) -> bool:
        """Junk-filter layer 2: most of the transcript (by characters) is labelled Cantonese."""
        yue = sum(len(t) for t, lang in self.segments if lang.lower().startswith("yue"))
        total = sum(len(t) for t, _ in self.segments)
        return total > 0 and yue * 2 > total


class GoogleStt:
    """Chirp 3 via Speech-to-Text V2, sync Recognize."""

    def __init__(self, cfg: dict, project: str):
        self.model = cfg["model"]
        self.boost = cfg.get("phrase_boost", 10)
        self.recognizer = f"projects/{project}/locations/{cfg['location']}/recognizers/_"
        self.client = SpeechClient(client_options=ClientOptions(api_endpoint=cfg["endpoint"]))

    def _config(
        self, languages: list[str], phrases: list[str] | None, decoding: dict
    ) -> cs.RecognitionConfig:
        config = cs.RecognitionConfig(
            model=self.model,
            language_codes=languages,
            features=cs.RecognitionFeatures(enable_automatic_punctuation=True),
            **decoding,
        )
        if phrases:
            phrase_set = cs.PhraseSet(
                phrases=[cs.PhraseSet.Phrase(value=p, boost=self.boost) for p in phrases]
            )
            config.adaptation = cs.SpeechAdaptation(
                phrase_sets=[cs.SpeechAdaptation.AdaptationPhraseSet(inline_phrase_set=phrase_set)]
            )
        return config

    def transcribe(
        self, wav: bytes, languages: list[str], phrases: list[str] | None = None
    ) -> SttResult:
        config = self._config(
            languages, phrases, {"auto_decoding_config": cs.AutoDetectDecodingConfig()}
        )
        start = perf_counter()
        response = self.client.recognize(
            request=cs.RecognizeRequest(recognizer=self.recognizer, config=config, content=wav)
        )
        latency = perf_counter() - start
        segments = [
            (r.alternatives[0].transcript.strip(), r.language_code or "")
            for r in response.results
            if r.alternatives and r.alternatives[0].transcript.strip()
        ]
        return SttResult(
            text=" ".join(t for t, _ in segments), latency_s=latency, segments=segments
        )


@dataclass
class StreamFinal:
    text: str
    language: str
    received_s: float  # when it arrived, seconds after the first audio frame was sent
    audio_end_s: float  # where in the audio this result ends (Chirp 3's result_end_offset)


@dataclass
class StreamResult:
    finals: list[StreamFinal]
    speech_end_s: float  # when the last speech frame was sent (before any trailing silence)
    sent_all_s: float  # when the last frame (incl. trailing silence) was sent
    first_interim_s: float | None
    events: list[tuple[str, float]]  # voice-activity events: (type, received_s)

    @property
    def text(self) -> str:
        return " ".join(f.text for f in self.finals)

    @property
    def segments(self) -> list[tuple[str, str]]:
        return [(f.text, f.language) for f in self.finals]

    @property
    def finalize_latency_s(self) -> float | None:
        """End of speech → last final transcript: the delay streaming is meant to shrink."""
        return self.finals[-1].received_s - self.speech_end_s if self.finals else None


_Sensitivity = cs.StreamingRecognitionFeatures.EndpointingSensitivity
_ENDPOINTING = {
    "standard": _Sensitivity.ENDPOINTING_SENSITIVITY_STANDARD,
    "short": _Sensitivity.ENDPOINTING_SENSITIVITY_SHORT,
    "supershort": _Sensitivity.ENDPOINTING_SENSITIVITY_SUPERSHORT,
}


class GoogleStreamingStt(GoogleStt):
    """Chirp 3 StreamingRecognize: audio is sent at real-time pace, as the hub would send it.

    Google's limits: one stream lasts at most 5 minutes, each message carries at most 25 KB of
    audio (100 ms of 16 kHz PCM is 3.2 KB), and audio must arrive at about real-time speed."""

    def stream(
        self,
        pcm: bytes,
        languages: list[str],
        phrases: list[str] | None = None,
        rate: int = 16_000,
        frame_ms: int = 100,
        tail_silence_s: float = 1.0,
        endpointing: str = "standard",
    ) -> StreamResult:
        """pcm: raw mono 16-bit samples. Trailing silence lets Chirp 3 notice the pause."""
        decoding = {
            "explicit_decoding_config": cs.ExplicitDecodingConfig(
                encoding=cs.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=rate,
                audio_channel_count=1,
            )
        }
        streaming_config = cs.StreamingRecognitionConfig(
            config=self._config(languages, phrases, decoding),
            streaming_features=cs.StreamingRecognitionFeatures(
                interim_results=True,
                enable_voice_activity_events=True,
                endpointing_sensitivity=_ENDPOINTING[endpointing],
            ),
        )
        frame_bytes = rate * 2 * frame_ms // 1000
        speech_frames = [pcm[i : i + frame_bytes] for i in range(0, len(pcm), frame_bytes)]
        silence_frames = [bytes(frame_bytes)] * round(tail_silence_s * 1000 / frame_ms)
        timing = {"start": None, "speech_end": 0.0, "sent_all": 0.0}

        def requests():
            yield cs.StreamingRecognizeRequest(
                recognizer=self.recognizer, streaming_config=streaming_config
            )
            timing["start"] = perf_counter()
            frames = speech_frames + silence_frames
            for i, frame in enumerate(frames):
                # Real-time pace: frame i goes out at i * frame_ms after the start.
                delay = timing["start"] + i * frame_ms / 1000 - perf_counter()
                if delay > 0:
                    time.sleep(delay)
                yield cs.StreamingRecognizeRequest(audio=frame)
                now = perf_counter() - timing["start"]
                if i == len(speech_frames) - 1:
                    timing["speech_end"] = now
                timing["sent_all"] = now

        finals, events, first_interim = [], [], None
        for response in self.client.streaming_recognize(requests=requests()):
            now = perf_counter() - (timing["start"] or perf_counter())
            if response.speech_event_type:
                events.append(
                    (
                        cs.StreamingRecognizeResponse.SpeechEventType(
                            response.speech_event_type
                        ).name,
                        round(now, 3),
                    )
                )
            for result in response.results:
                if not result.alternatives:
                    continue
                text = result.alternatives[0].transcript.strip()
                if result.is_final:
                    if text:
                        finals.append(
                            StreamFinal(
                                text=text,
                                language=result.language_code or "",
                                received_s=round(now, 3),
                                audio_end_s=result.result_end_offset.total_seconds(),
                            )
                        )
                elif text and first_interim is None:
                    first_interim = round(now, 3)
        return StreamResult(
            finals=finals,
            speech_end_s=round(timing["speech_end"], 3),
            sent_all_s=round(timing["sent_all"], 3),
            first_interim_s=first_interim,
            events=events,
        )


# OpenAI takes ISO-639-1 hints only; Cantonese has none, so it gets no hint.
_OPENAI_LANGUAGE = {"cmn-Hans-CN": "zh", "en-US": "en"}


class OpenAiStt:
    def __init__(self, model: str):
        self.model = model
        self.client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), max_retries=0)

    def transcribe(
        self, wav: bytes, languages: list[str], phrases: list[str] | None = None
    ) -> SttResult:
        kwargs = {}
        if len(languages) == 1 and languages[0] in _OPENAI_LANGUAGE:
            kwargs["language"] = _OPENAI_LANGUAGE[languages[0]]
        if phrases:
            kwargs["prompt"] = "Places and dishes: " + ", ".join(phrases)
        start = perf_counter()
        response = self.client.audio.transcriptions.create(
            model=self.model, file=("chunk.wav", wav, "audio/wav"), **kwargs
        )
        return SttResult(text=response.text.strip(), latency_s=perf_counter() - start)
