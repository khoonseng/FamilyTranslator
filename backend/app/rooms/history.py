"""Read-only access to the room's saved conversations."""

import asyncio
from datetime import date, timedelta
from time import monotonic

from app.schemas import (
    HistoryClip,
    HistoryClipRequest,
    HistoryDays,
    HistoryDaysRequest,
    HistoryPage,
    HistorySentence,
)

HISTORY_DAYS = 30
PAGE_BUBBLES = 24


class HistoryArchive:
    def __init__(self, store, today):
        self.store = store
        self.today = today
        self._lock = asyncio.Lock()
        self._cached_day = ""
        self._cached_until = 0.0
        self._bubbles: list[list[dict]] = []

    def invalidate(self, day: str) -> None:
        if day == self._cached_day:
            self._cached_day = ""

    async def response(self, request):
        today = date.fromisoformat(self.today())
        first = today - timedelta(days=HISTORY_DAYS)
        request_id = request.request_id
        if isinstance(request, HistoryDaysRequest):
            days = await self.store.history_dates(first.isoformat(), today.isoformat())
            return HistoryDays(request_id=request_id, days=days), None

        day = request.day
        can_read = first <= day < today
        if isinstance(request, HistoryClipRequest):
            clip = None
            if can_read:
                clip = await self.store.read_history_clip(day.isoformat(), request.sentence_id)
            return HistoryClip(
                request_id=request_id,
                day=day,
                sentence_id=request.sentence_id,
                bytes=len(clip or b""),
            ), clip

        bubbles = await self._load(day.isoformat()) if can_read else []
        remaining = [bubble for bubble in bubbles if bubble[0]["id"] > request.after]
        page = remaining[:PAGE_BUBBLES]
        return HistoryPage(
            request_id=request_id,
            day=day,
            sentences=[
                HistorySentence.model_validate(
                    {
                        **record,
                        "clip": (
                            "ready"
                            if record.get("kind") != "reply" and record.get("clip") == "ready"
                            else "none"
                        ),
                    }
                )
                for bubble in page
                for record in bubble
            ],
            next_after=page[-1][0]["id"] if len(remaining) > PAGE_BUBBLES else None,
        ), None

    async def _load(self, day: str) -> list[list[dict]]:
        # Fetch a day once for neighbouring pages. Group by the original bubble even
        # when a reply arrived between two of its sentences.
        async with self._lock:
            if day != self._cached_day or monotonic() >= self._cached_until:
                self._cached_day = day
                self._cached_until = 0.0
                records = await self.store.read_history_day(day)
                bubbles: dict[int, list[dict]] = {}
                for record in records:
                    bubbles.setdefault(record["bubble_id"], []).append(record)
                self._bubbles = list(bubbles.values())
                if self._cached_day == day:
                    self._cached_until = monotonic() + 30
            return self._bubbles
