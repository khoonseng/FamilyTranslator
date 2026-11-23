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
    family_tts: GoogleTts  # speaks guide sentences to the family (Chongqing: Cantonese)
    stt: GoogleStreamingStt
    transcribe: OpenAiTranscribe
    guide_tts: GoogleTts  # speaks family replies to the guide (Chongqing: Mandarin; phase 2)


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
    # STT phrase hints: the glossary column in the guide's language (Chongqing: `zh`).
    phrases = [term[cfg["stt"]["google"]["hint_column"]] for term in config.glossary()]
    return Providers(
        translator=Translator(
            models,
            CloudTranslate(tr["cloud_translate"], project, tr["timeout_s"]),
            tr["yue_deadline_s"],
            tr["timeout_s"],
        ),
        family_tts=GoogleTts(cfg["tts"]["family_voice"]),
        stt=GoogleStreamingStt(cfg["stt"]["google"], project, phrases),
        transcribe=OpenAiTranscribe(cfg["stt"]["openai"], phrases),
        guide_tts=GoogleTts(cfg["tts"]["guide_voice"]),
    )
