"""Provider adapters (hard rule 6), built from config.yaml. Business logic uses `Providers`
and the types in app.providers.base, never a provider SDK."""

from dataclasses import dataclass

from app import config
from app.providers.llm import ChatModel
from app.providers.mt import CloudTranslate
from app.providers.stt import GoogleStreamingStt, OpenAiTranscribe
from app.providers.translator import Translator
from app.providers.tts import GoogleTts


@dataclass
class Providers:
    translator: Translator
    tts: GoogleTts
    stt: GoogleStreamingStt
    transcribe: OpenAiTranscribe


def build(cfg: dict | None = None) -> Providers:
    cfg = cfg or config.load()
    tr = cfg["translation"]
    models = [
        ChatModel(
            name,
            tr["models"][name],
            tr["providers"][tr["models"][name]["provider"]],
            tr["timeout_s"],
        )
        for name in tr["order"]
    ]
    project = config.project()
    phrases = [term["zh"] for term in config.glossary()]
    return Providers(
        translator=Translator(
            models,
            CloudTranslate(tr["cloud_translate"], project, tr["timeout_s"]),
            tr["yue_deadline_s"],
            tr["timeout_s"],
        ),
        tts=GoogleTts(cfg["tts"]["google"]),
        stt=GoogleStreamingStt(cfg["stt"]["google"], project, phrases),
        transcribe=OpenAiTranscribe(cfg["stt"]["openai"], phrases),
    )
