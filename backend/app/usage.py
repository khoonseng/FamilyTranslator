"""The spending meter (architecture doc, "App-side spending alert").

The pipeline reports each day's usage here: speech-to-text seconds, translation tokens,
Cloud Translation characters and text-to-speech characters. Prices come from config.yaml.
The estimate goes to host phones only, with a warning above the daily threshold; it never
pauses or stops translation. Counts only, never text (hard rule 14)."""

from collections import defaultdict


class Meter:
    def __init__(self, counts: dict | None = None):
        # kind -> name -> units: stt seconds, llm_in / llm_out tokens, mt / tts characters
        self.counts: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for kind, names in (counts or {}).items():
            for name, units in names.items():
                self.counts[kind][name] = units
        self.changed = False

    def _add(self, kind: str, name: str, units: float) -> None:
        if units > 0:
            self.counts[kind][name] += units
            self.changed = True

    def stt(self, name: str, seconds: float) -> None:
        self._add("stt", name, seconds)

    def llm(self, name: str, input_tokens: int, output_tokens: int) -> None:
        self._add("llm_in", name, input_tokens)
        self._add("llm_out", name, output_tokens)

    def mt(self, characters: int) -> None:
        self._add("mt", "cloud-translate", characters)

    def tts(self, voice: str, characters: int) -> None:
        self._add("tts", voice, characters)

    def cost(self, prices: dict) -> float:
        """US$ for the day. Unpriced names count as zero (and show up in the tests)."""
        total = 0.0
        for name, seconds in self.counts["stt"].items():
            total += seconds / 60 * prices["stt_per_minute"].get(name, 0)
        for kind in ("llm_in", "llm_out"):
            per_million = prices["llm_per_million_" + kind.removeprefix("llm_")]
            for name, tokens in self.counts[kind].items():
                total += tokens / 1e6 * per_million.get(name, 0)
        for chars in self.counts["mt"].values():
            total += chars / 1e6 * prices["mt_per_million_chars"]
        for voice, chars in self.counts["tts"].items():
            tier = "chirp3_hd" if "Chirp3-HD" in voice else "standard"
            total += chars / 1e6 * prices["tts_per_million_chars"][tier]
        return total

    def to_dict(self) -> dict:
        return {kind: dict(names) for kind, names in self.counts.items()}
