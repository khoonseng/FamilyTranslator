"""Google Cloud Translation v3 (NMT): the last-resort translator, used only when every LLM has
failed on a sentence (hard rule 4). Two calls, no context, literal wording: `yue` and `en` for
the guide's Mandarin; `zh-CN` and the family's other language for a reply (phase 2), whose
source language Google detects. Authenticates with the service account (hard rule 6)."""

import asyncio

from google.cloud import translate_v3 as tr


class CloudTranslate:
    name = "cloud-translate"

    def __init__(self, cfg: dict, project: str, timeout_s: float):
        self.parent = f"projects/{project}/locations/{cfg['location']}"
        self.timeout_s = timeout_s
        self._client = None  # created on first use, inside the event loop

    async def _translate(self, text: str, target: str, source: str) -> str:
        if self._client is None:
            self._client = tr.TranslationServiceAsyncClient()
        response = await self._client.translate_text(
            request=tr.TranslateTextRequest(
                parent=self.parent,
                contents=[text],
                mime_type="text/plain",
                target_language_code=target,
                **({"source_language_code": source} if source else {}),
            ),
            timeout=self.timeout_s,
        )
        return response.translations[0].translated_text

    def translate(
        self, text: str, targets: tuple[str, str] = ("yue", "en")
    ) -> tuple[asyncio.Task, asyncio.Task]:
        """Starts both calls at once and returns their tasks, in the order of `targets`. The
        guide's text is Mandarin; a reply's language is left for Google to detect."""
        source = "zh-CN" if targets == ("yue", "en") else ""
        return (
            asyncio.ensure_future(self._translate(text, targets[0], source)),
            asyncio.ensure_future(self._translate(text, targets[1], source)),
        )
