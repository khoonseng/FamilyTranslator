"""Google Cloud Translation v3, standard (NMT) model. Text only; one call per target language.

Bake-off candidate (added 2026-10-14). Cantonese (`yue`) is supported only by the NMT model,
so there is no style instruction and no context, just the sentence (and optionally a glossary)."""

from dataclasses import dataclass
from time import perf_counter

from google.cloud import translate_v3 as tr


@dataclass
class MtResult:
    text: str
    latency_s: float


class CloudTranslate:
    def __init__(self, cfg: dict, project: str):
        self.parent = f"projects/{project}/locations/{cfg['location']}"
        self.glossary_id = cfg.get("glossary_id")
        self.client = tr.TranslationServiceClient()

    def translate(
        self, text: str, source: str, target: str, use_glossary: bool = False
    ) -> MtResult:
        """source/target: Cloud Translation codes, e.g. zh-CN, yue, en."""
        request = tr.TranslateTextRequest(
            parent=self.parent,
            contents=[text],
            mime_type="text/plain",
            source_language_code=source,
            target_language_code=target,
        )
        if use_glossary:
            if not self.glossary_id:
                raise RuntimeError("mt.google.glossary_id is not set in config.yaml")
            request.glossary_config = tr.TranslateTextGlossaryConfig(
                glossary=f"{self.parent}/glossaries/{self.glossary_id}"
            )
        start = perf_counter()
        response = self.client.translate_text(request=request)
        latency = perf_counter() - start
        translations = response.glossary_translations if use_glossary else response.translations
        return MtResult(text=translations[0].translated_text, latency_s=latency)
