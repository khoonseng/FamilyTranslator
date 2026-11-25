"""Where the room keeps what it must not lose on a restart (architecture doc, "Storage").

Layout in the private bucket:
- `days/<YYYY-MM-DD>/sentences/<id>.json`: one small record per sentence (Cloud Storage
  objects can't be appended to, so one object each);
- `days/<YYYY-MM-DD>/clips/<id>.mp3`: the sentence's Cantonese clip;
- `days/<YYYY-MM-DD>/usage.json`: the day's usage counters (spending meter);
- `settings/join.json`: the join link's room token.

The bucket deletes `days/` objects after 30 days (hard rule 14's exception for our own
storage); `settings/` never expires, so the join link outlives the rule. Without a bucket
(tests, local runs) everything lives in memory."""

from __future__ import annotations

import asyncio
import json

from google.cloud import storage
from google.cloud.exceptions import NotFound


class MemoryStore:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    async def put(self, name: str, data: bytes, content_type: str) -> None:
        self.objects[name] = data

    async def get(self, name: str) -> bytes | None:
        return self.objects.get(name)

    read = get

    async def list(self, prefix: str) -> list[str]:
        return sorted(name for name in self.objects if name.startswith(prefix))

    async def folders(self, prefix: str) -> list[str]:
        return sorted(
            {
                f"{prefix}{name[len(prefix) :].split('/', 1)[0]}/"
                for name in self.objects
                if name.startswith(prefix) and "/" in name[len(prefix) :]
            }
        )

    async def has_objects(self, prefix: str) -> bool:
        return any(name.startswith(prefix) for name in self.objects)


class GcsStore:
    def __init__(self, bucket: str, project: str):
        self._bucket = storage.Client(project=project).bucket(bucket)

    async def put(self, name: str, data: bytes, content_type: str) -> None:
        blob = self._bucket.blob(name)
        await asyncio.to_thread(blob.upload_from_string, data, content_type=content_type)

    async def get(self, name: str) -> bytes | None:
        try:
            return await self.read(name)
        except Exception:  # noqa: BLE001 - missing or unreadable: the caller copes
            return None

    async def read(self, name: str) -> bytes | None:
        blob = self._bucket.blob(name)
        try:
            return await asyncio.to_thread(blob.download_as_bytes)
        except NotFound:
            return None

    async def list(self, prefix: str) -> list[str]:
        blobs = await asyncio.to_thread(lambda: list(self._bucket.list_blobs(prefix=prefix)))
        return sorted(blob.name for blob in blobs)

    async def folders(self, prefix: str) -> list[str]:
        def list_prefixes() -> list[str]:
            blobs = self._bucket.list_blobs(prefix=prefix, delimiter="/")
            for _ in blobs.pages:
                pass  # prefixes are populated as pages arrive
            return sorted(blobs.prefixes)

        return await asyncio.to_thread(list_prefixes)

    async def has_objects(self, prefix: str) -> bool:
        def any_blob() -> bool:
            blobs = self._bucket.list_blobs(prefix=prefix, max_results=1)
            return next(iter(blobs), None) is not None

        return await asyncio.to_thread(any_blob)


class RoomStore:
    """The room's view of a store: sentences, clips, usage and the join link."""

    def __init__(self, backend):
        self.backend = backend

    async def put_sentence(self, day: str, record: dict) -> None:
        data = json.dumps(record, ensure_ascii=False).encode()
        name = f"days/{day}/sentences/{record['id']:05d}.json"
        await self.backend.put(name, data, "application/json")

    async def put_clip(self, day: str, sentence_id: int, mp3: bytes) -> None:
        await self.backend.put(f"days/{day}/clips/{sentence_id:05d}.mp3", mp3, "audio/mpeg")

    async def get_clip(self, day: str, sentence_id: int) -> bytes | None:
        return await self.backend.get(f"days/{day}/clips/{sentence_id:05d}.mp3")

    async def read_history_clip(self, day: str, sentence_id: int) -> bytes | None:
        record = await self.backend.read(f"days/{day}/sentences/{sentence_id:05d}.json")
        if record is None:
            return None
        sentence = json.loads(record)
        if sentence.get("clip") != "ready" or sentence.get("kind") == "reply":
            return None
        return await self.backend.read(f"days/{day}/clips/{sentence_id:05d}.mp3")

    async def history_dates(self, first: str, today: str) -> list[str]:
        candidates = [
            folder.removeprefix("days/").removesuffix("/")
            for folder in await self.backend.folders("days/")
        ]
        days = sorted((day for day in candidates if first <= day < today), reverse=True)
        exists = await asyncio.gather(
            *(self.backend.has_objects(f"days/{day}/sentences/") for day in days)
        )
        return [day for day, present in zip(days, exists, strict=True) if present]

    async def read_history_day(self, day: str) -> list[dict]:
        names = await self.backend.list(f"days/{day}/sentences/")
        records = []
        for offset in range(0, len(names), 12):
            names_in_batch = names[offset : offset + 12]
            batch = await asyncio.gather(*(self.backend.read(name) for name in names_in_batch))
            records.extend(json.loads(data) for data in batch if data)
        return sorted(records, key=lambda record: record["id"])

    async def load_day(self, day: str) -> list[dict]:
        records = []
        for name in await self.backend.list(f"days/{day}/sentences/"):
            data = await self.backend.get(name)
            if data:
                records.append(json.loads(data))
        return sorted(records, key=lambda r: r["id"])

    async def get_json(self, name: str) -> dict | None:
        data = await self.backend.get(name)
        return json.loads(data) if data else None

    async def put_json(self, name: str, value: dict) -> None:
        await self.backend.put(name, json.dumps(value).encode(), "application/json")
