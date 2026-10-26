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

import asyncio
import json

from google.cloud import storage


class MemoryStore:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    async def put(self, name: str, data: bytes, content_type: str) -> None:
        self.objects[name] = data

    async def get(self, name: str) -> bytes | None:
        return self.objects.get(name)

    async def list(self, prefix: str) -> list[str]:
        return sorted(name for name in self.objects if name.startswith(prefix))


class GcsStore:
    def __init__(self, bucket: str, project: str):
        self._bucket = storage.Client(project=project).bucket(bucket)

    async def put(self, name: str, data: bytes, content_type: str) -> None:
        blob = self._bucket.blob(name)
        await asyncio.to_thread(blob.upload_from_string, data, content_type=content_type)

    async def get(self, name: str) -> bytes | None:
        blob = self._bucket.blob(name)
        try:
            return await asyncio.to_thread(blob.download_as_bytes)
        except Exception:  # noqa: BLE001 - missing or unreadable: the caller copes
            return None

    async def list(self, prefix: str) -> list[str]:
        blobs = await asyncio.to_thread(lambda: list(self._bucket.list_blobs(prefix=prefix)))
        return sorted(blob.name for blob in blobs)


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
