"""Speech-to-text adapters: Google Chirp 3 (sync Recognize only) and OpenAI transcription."""

import os
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
    languages: list[str] = field(default_factory=list)  # per-result labels (Chirp 3 only)


class GoogleStt:
    """Chirp 3 via Speech-to-Text V2. Sync Recognize only: never the batch endpoint (rule 14)."""

    def __init__(self, cfg: dict, project: str):
        self.model = cfg["model"]
        self.boost = cfg.get("phrase_boost", 10)
        self.recognizer = f"projects/{project}/locations/{cfg['location']}/recognizers/_"
        self.client = SpeechClient(client_options=ClientOptions(api_endpoint=cfg["endpoint"]))

    def transcribe(
        self, wav: bytes, languages: list[str], phrases: list[str] | None = None
    ) -> SttResult:
        config = cs.RecognitionConfig(
            auto_decoding_config=cs.AutoDetectDecodingConfig(),
            model=self.model,
            language_codes=languages,
            features=cs.RecognitionFeatures(enable_automatic_punctuation=True),
        )
        if phrases:
            phrase_set = cs.PhraseSet(
                phrases=[cs.PhraseSet.Phrase(value=p, boost=self.boost) for p in phrases]
            )
            config.adaptation = cs.SpeechAdaptation(
                phrase_sets=[cs.SpeechAdaptation.AdaptationPhraseSet(inline_phrase_set=phrase_set)]
            )
        start = perf_counter()
        response = self.client.recognize(
            request=cs.RecognizeRequest(recognizer=self.recognizer, config=config, content=wav)
        )
        latency = perf_counter() - start
        results = [r for r in response.results if r.alternatives]
        return SttResult(
            text=" ".join(r.alternatives[0].transcript.strip() for r in results).strip(),
            latency_s=latency,
            languages=[r.language_code for r in results if r.language_code],
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
