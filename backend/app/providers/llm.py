"""The ONE OpenAI-compatible chat client (hard rule 6): Gemini on Vertex AI and Qwen on Groq
are config entries (config.yaml, translation.models), not separate code.

Vertex AI authenticates with a short-lived Google access token (the Cloud Run service account,
or Application Default Credentials locally), refreshed before it expires; Groq uses its key."""

import asyncio
import os
from collections.abc import AsyncIterator

import google.auth
import google.auth.transport.requests
from openai import AsyncOpenAI

_GOOGLE_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


class ChatModel:
    def __init__(self, name: str, entry: dict, provider: dict, timeout_s: float):
        self.name = name
        self.model = entry["model"]
        self.temperature = entry.get("temperature")
        self.params = entry.get("params") or {}
        self.deadline = bool(entry.get("deadline"))
        self._auth = provider["auth"]
        self._google_creds = None
        self._client = AsyncOpenAI(
            base_url=provider["base_url"],
            api_key=os.environ.get(self._auth) or "pending",
            timeout=timeout_s,
            max_retries=0,  # failover, never retry (hard rule 6)
        )

    async def _authed(self) -> AsyncOpenAI:
        if self._auth == "google":
            if self._google_creds is None:
                self._google_creds, _ = await asyncio.to_thread(
                    google.auth.default, scopes=_GOOGLE_SCOPES
                )
            if not self._google_creds.valid:
                await asyncio.to_thread(
                    self._google_creds.refresh, google.auth.transport.requests.Request()
                )
            self._client.api_key = self._google_creds.token
        elif not os.environ.get(self._auth):
            raise RuntimeError(f"{self._auth} is not set")
        return self._client

    async def warm_up(self) -> None:
        """Fetches the Vertex access token ahead of the first sentence, so it doesn't eat into
        Gemini's deadline. Costs nothing: no model call."""
        if self._auth == "google":
            await self._authed()

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        """Yields the reply's text as it streams in, in JSON mode."""
        kwargs = {
            "model": self.model,
            "messages": messages,
            "extra_body": self.params,
            "response_format": {"type": "json_object"},
            "stream": True,
        }
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        client = await self._authed()
        chunks = await client.chat.completions.create(**kwargs)
        async for chunk in chunks:
            for choice in chunk.choices:
                if choice.delta and choice.delta.content:
                    yield choice.delta.content
