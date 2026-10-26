"""Bubbles, the voice notes listeners see (hard rule 9): a new bubble starts after a pause
longer than 2 s, or when the current one reaches 45 s of audio or 6 sentences. Sentences never
wait for a bubble to end; a bubble only groups them."""


class Bubbles:
    def __init__(self, pause_s: float, max_audio_s: float, max_sentences: int):
        self.pause_s = pause_s
        self.max_audio_s = max_audio_s
        self.max_sentences = max_sentences
        self.current: int | None = None
        self._next = 1
        self._audio_s: dict[int, float] = {}
        self._sentences: dict[int, int] = {}
        self._moved_to: dict[int, int] = {}  # a full bubble -> the one that continues it

    def resume(self, next_bubble: int) -> None:
        """After a restart: carry on numbering; the next segment starts a new bubble."""
        self._next = next_bubble
        self.current = None

    def new(self) -> int:
        bubble = self._next
        self._next += 1
        self._audio_s[bubble] = 0.0
        self._sentences[bubble] = 0
        self.current = bubble
        return bubble

    def on_segment(self, pause_s: float) -> int:
        """A segment starts after `pause_s` of silence: the bubble its speech belongs to."""
        current = self._latest(self.current) if self.current else None
        if (
            current is None
            or pause_s > self.pause_s
            or self._audio_s[current] >= self.max_audio_s
            or self._sentences[current] >= self.max_sentences
        ):
            return self.new()
        return current

    def add_audio(self, bubble: int, seconds: float) -> None:
        self._audio_s[self._latest(bubble)] += seconds

    def on_sentence(self, bubble: int) -> int:
        """A sentence spoken in `bubble`: the bubble it goes into, a continuation if full."""
        bubble = self._latest(bubble)
        if self._sentences[bubble] >= self.max_sentences:
            continuation = self.new()
            self._moved_to[bubble] = continuation
            bubble = continuation
        self._sentences[bubble] += 1
        return bubble

    def _latest(self, bubble: int) -> int:
        while bubble in self._moved_to:
            bubble = self._moved_to[bubble]
        return bubble
