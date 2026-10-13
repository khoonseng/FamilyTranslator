"""The ONE OpenAI-compatible chat client (hard rule 6). Vertex AI and Groq are config entries.

Vertex AI authenticates with a short-lived Google access token (service account / ADC),
refreshed before it expires; Groq uses an API key from the environment."""

import os
from dataclasses import dataclass
from time import perf_counter

import google.auth
import google.auth.transport.requests
from openai import OpenAI

from lib import config

_GOOGLE_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


@dataclass
class ChatResult:
    text: str
    ttft_s: float | None  # time to first content token (streaming only)
    total_s: float
    usage: dict | None


def reasoning_tokens(usage: dict | None) -> int | None:
    details = (usage or {}).get("completion_tokens_details") or {}
    return details.get("reasoning_tokens")


class ChatClient:
    def __init__(self, config_name: str, cfg: dict | None = None):
        cfg = cfg or config.load()
        llm = cfg["llm"]
        entry = llm["configs"][config_name]
        provider = llm["providers"][entry["provider"]]
        self.name = config_name
        self.model = entry["model"]
        self.params = entry.get("params") or {}
        self.json_mode = provider.get("json_mode")
        self.temperature = llm.get("temperature")
        self._auth = provider["auth"]
        self._google_creds = None
        api_key = None if self._auth == "google" else os.environ.get(self._auth)
        self._client = OpenAI(
            base_url=provider["base_url"],
            api_key=api_key or "pending",
            timeout=llm.get("timeout_s", 20),
            max_retries=0,
        )

    def _client_with_auth(self) -> OpenAI:
        if self._auth == "google":
            if self._google_creds is None:
                self._google_creds, _ = google.auth.default(scopes=_GOOGLE_SCOPES)
            if not self._google_creds.valid:
                self._google_creds.refresh(google.auth.transport.requests.Request())
            self._client.api_key = self._google_creds.token
        elif not os.environ.get(self._auth):
            raise RuntimeError(f"{self._auth} is not set (bakeoff/.env)")
        return self._client

    def chat(self, messages: list[dict], stream: bool = True) -> ChatResult:
        kwargs = {"model": self.model, "messages": messages, "extra_body": self.params}
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if self.json_mode == "json_object":
            kwargs["response_format"] = {"type": "json_object"}
        client = self._client_with_auth()
        start = perf_counter()
        if not stream:
            response = client.chat.completions.create(**kwargs)
            return ChatResult(
                text=response.choices[0].message.content or "",
                ttft_s=None,
                total_s=perf_counter() - start,
                usage=response.usage.model_dump() if response.usage else None,
            )
        first, parts, usage = None, [], None
        chunks = client.chat.completions.create(
            stream=True, stream_options={"include_usage": True}, **kwargs
        )
        for chunk in chunks:
            if chunk.usage:
                usage = chunk.usage.model_dump()
            for choice in chunk.choices:
                if choice.delta and choice.delta.content:
                    if first is None:
                        first = perf_counter() - start
                    parts.append(choice.delta.content)
        return ChatResult(
            text="".join(parts), ttft_s=first, total_s=perf_counter() - start, usage=usage
        )


def translation_messages(direction: str, sentence: str, context: list[str]) -> list[dict]:
    """direction: "guide_to_family" or "family_to_guide" (the prompt file names)."""
    system = (
        config.prompt(direction)
        .replace("{glossary}", config.glossary_text())
        .replace("{context}", "\n".join(f"- {c}" for c in context) or "(none)")
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": sentence}]
