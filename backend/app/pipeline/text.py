"""Sentence splitting and the junk filter's text layers (hard rules 8 and 9)."""

import re
import unicodedata

# A sentence ends at Chinese or Western sentence enders plus any closing quotes, or at a full
# stop followed by a space (so 3.5 is not split). The punctuation stays with its sentence.
# Chirp 3 sometimes punctuates with ASCII commas and full stops (", ."), so those count too.
_SENTENCE_END = re.compile(r"([。！？!?；;…]+[」』”’\"']*|\.(?=\s|$))")


def split_sentences(text: str) -> list[str]:
    marked = _SENTENCE_END.sub(r"\1\n", text)
    return [s.strip() for s in marked.split("\n") if s.strip()]


def spoken_chars(text: str) -> str:
    """The text without punctuation, symbols and spaces."""
    return "".join(
        ch for ch in text if not unicodedata.category(ch).startswith(("P", "S", "Z", "C"))
    )


def cantonese_share(text: str, chars: list[str]) -> float:
    """Share of a sentence's characters that are Cantonese-only (哋, 唔, 喺 ...): junk-filter
    layer 2. Mandarin narration scores 0; family chatter scores high."""
    spoken = spoken_chars(text)
    return sum(spoken.count(ch) for ch in chars) / len(spoken) if spoken else 0.0


def drop_reason(sentence: str, cfg: dict) -> str | None:
    """Why the junk filter drops a Guide-mode sentence, or None to keep it. The reason is a
    label for the logs, never the text (hard rule 14)."""
    spoken = spoken_chars(sentence)
    filler = set(cfg["filler"])
    if spoken in filler or (spoken and not spoken.strip("".join(filler))):
        return "filler"
    if len(spoken) < cfg["min_chars"]:
        return "short"
    if cantonese_share(sentence, cfg["cantonese_only_chars"]) > cfg["cantonese_share"]:
        return "cantonese"
    return None
