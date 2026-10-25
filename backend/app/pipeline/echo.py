"""Junk-filter layer 4: echo detection (decided 2026-10-25).

If a listener phone plays on its speaker near the hub, the hub hears our own Cantonese and
would translate it again: the loop that ruined Traverba. Chirp 3 writes that Cantonese with
Mandarin characters (係 -> 系, 嘅 -> 慨), so the character filter (layer 2) caught only 1-3 of
31 such clips. Instead, each new guide sentence is compared with the translations sent in the
last minute; a close match is an echo. Bake-off check: 29 of 31 echoes caught at a mismatch
below 0.6, with no false alarms in 930 comparisons of real guide sentences (closest 0.67)."""

from collections import deque
from time import monotonic

from app.pipeline.text import mismatch


class EchoGuard:
    def __init__(self, window_s: float, max_mismatch: float, now=monotonic):
        self.window_s = window_s
        self.max_mismatch = max_mismatch
        self.now = now
        self._recent: deque[tuple[float, str]] = deque()

    def remember(self, translation: str) -> None:
        self._recent.append((self.now(), translation))

    def is_echo(self, sentence: str) -> bool:
        cutoff = self.now() - self.window_s
        while self._recent and self._recent[0][0] < cutoff:
            self._recent.popleft()
        return any(mismatch(yue, sentence) < self.max_mismatch for _, yue in self._recent)
