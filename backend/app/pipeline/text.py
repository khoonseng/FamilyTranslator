"""Sentence splitting and the junk filter's text layers (hard rules 8 and 9)."""

import re
import unicodedata

from opencc import OpenCC

_to_simplified = OpenCC("t2s")

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


_COMPLETE = re.compile(r"[。！？!?；;…][」』”’\"']*$|\.$")


def is_complete(sentence: str) -> bool:
    """Ends with sentence-ending punctuation. A segment cut off by a mid-sentence pause usually
    doesn't (Chirp 3 left 4 of 6 such cut-offs unpunctuated), so the pipeline holds it briefly
    for the rest of the sentence (decided 2026-10-25)."""
    return bool(_COMPLETE.search(sentence.strip()))


_DIGITS = "零一二三四五六七八九"


def _chinese_number(n: int) -> str:
    """0-9999 as spoken numerals: 5 -> 五, 40 -> 四十, 15 -> 十五, 105 -> 一百零五."""
    if n < 10:
        return _DIGITS[n]
    out, zero = "", False
    for value, unit in ((1000, "千"), (100, "百"), (10, "十"), (1, "")):
        d, n = divmod(n, value)
        if d:
            if zero:
                out += "零"
            out += ("" if (unit == "十" and d == 1 and not out) else _DIGITS[d]) + unit
            zero = False
        elif out:
            zero = True
    return out


def comparable(text: str) -> str:
    """Spoken characters only, in Simplified, numbers as numerals: 七點半 and 7点半 match."""
    text = spoken_chars(text).lower()
    text = re.sub(r"\d{1,4}", lambda m: _chinese_number(int(m.group())), text)
    return _to_simplified.convert(text)


def edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def mismatch(reference: str, heard: str) -> float:
    """Edits needed to turn `heard` into `reference`, per reference character (0 = identical)."""
    ref, hyp = comparable(reference), comparable(heard)
    if not ref:
        return 1.0
    return edit_distance(ref, hyp) / len(ref)
