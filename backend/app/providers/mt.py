"""Google Cloud Translation v3 (NMT): the last-resort translator, used only when every LLM has
failed on a sentence (hard rule 4). Two calls, `yue` and `en`, no context, literal wording.
Authenticates with the service account (hard rule 6)."""

import asyncio

from google.cloud import translate_v3 as tr


class CloudTranslate:
    name = "cloud-translate"

    def __init__(self, cfg: dict, project: str, timeout_s: float):
        self.parent = f"projects/{project}/locations/{cfg['location']}"
        self.timeout_s = timeout_s
        self._client = None  # created on first use, inside the event loop

    async def _translate(self, text: str, target: str) -> str:
        if self._client is None:
            self._client = tr.TranslationServiceAsyncClient()
        response = await self._client.translate_text(
            request=tr.TranslateTextRequest(
                parent=self.parent,
                contents=[text],
                mime_type="text/plain",
                source_language_code="zh-CN",
                target_language_code=target,
            ),
            timeout=self.timeout_s,
        )
        return response.translations[0].translated_text

    def translate(self, text: str) -> tuple[asyncio.Task, asyncio.Task]:
        """Starts both calls at once and returns (yue task, en task)."""
        return (
            asyncio.ensure_future(self._translate(text, "yue")),
            asyncio.ensure_future(self._translate(text, "en")),
        )
