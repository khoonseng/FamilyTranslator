"""Scores for STT and translation output. Pure functions, no provider calls."""

import json
import re
import unicodedata

from opencc import OpenCC

_to_simplified = OpenCC("t2s")
_to_traditional = OpenCC("s2t")


def strip_punct(text: str) -> str:
    """Drop punctuation, symbols and whitespace so only the spoken characters are compared."""
    return "".join(
        ch for ch in text if not unicodedata.category(ch).startswith(("P", "S", "Z", "C"))
    )


_DIGITS = "零一二三四五六七八九"


def chinese_number(n: int) -> str:
    """0-9999 as spoken Chinese numerals: 5 -> 五, 40 -> 四十, 15 -> 十五, 105 -> 一百零五."""
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


def normalize(text: str, script: str = "simplified") -> str:
    """Punctuation-free, lower-cased text in one Chinese script, with Arabic numbers written as
    Chinese numerals (6点钟 = 六点钟), for a fair comparison."""
    text = strip_punct(text).lower()
    text = re.sub(r"\d{1,4}", lambda m: chinese_number(int(m.group())), text)
    return _to_simplified.convert(text) if script == "simplified" else _to_traditional.convert(text)


def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def char_edits(reference: str, hypothesis: str, script: str = "simplified") -> tuple[int, int]:
    """(edits, reference length) after normalising, so error rates can be pooled over chunks."""
    ref, hyp = normalize(reference, script), normalize(hypothesis, script)
    return edit_distance(ref, hyp), len(ref)


def cer(reference: str, hypothesis: str, script: str = "simplified") -> float:
    """Character error rate: edits needed to turn the hypothesis into the reference,
    divided by the reference length. 0.0 is perfect; can exceed 1.0."""
    edits, length = char_edits(reference, hypothesis, script)
    if not length:
        return 0.0 if not edits else 1.0
    return edits / length


def count_markers(text: str, markers: list[str], exceptions: list[str] = ()) -> int:
    """Count marker occurrences, longest marker first, so 他們 is not also counted as 他 + 們.
    Exception words are removed first."""
    for word in exceptions:
        text = text.replace(word, "\0")
    total = 0
    for marker in sorted(markers, key=len, reverse=True):
        total += text.count(marker)
        text = text.replace(marker, "\0")
    return total


def colloquial_score(text: str, scoring_cfg: dict) -> dict:
    """How spoken-Cantonese the text is: colloquial markers vs formal written-Chinese forms."""
    colloquial = count_markers(text, scoring_cfg["colloquial_markers"])
    formal = count_markers(
        text, scoring_cfg["formal_markers"], scoring_cfg.get("formal_exceptions", [])
    )
    total = colloquial + formal
    return {
        "colloquial": colloquial,
        "formal": formal,
        "ratio": colloquial / total if total else None,
    }


def cantonese_char_count(text: str, chars: list[str]) -> int:
    """How many Cantonese-only characters (哋, 唔, 喺 ...) a transcript contains."""
    return sum(text.count(ch) for ch in chars)


def cantonese_share(text: str, chars: list[str]) -> float:
    """Share of a sentence's characters that are Cantonese-only. Junk-filter layer 2 drops a
    Guide-mode sentence above a threshold; Mandarin narration should score 0."""
    length = len(strip_punct(text))
    return cantonese_char_count(text, chars) / length if length else 0.0


_LATIN_WORD = re.compile(r"[A-Za-z]{2,}")
_LOOP = re.compile(r"(.{1,8}?)\1{3,}")


def glitches(text: str) -> list[str]:
    """Output defects the colloquial score can't see: stray English words inside Cantonese
    (`四十 processing 分鐘`) and runaway repetition (`聽住，聽住，聽住，…`). The TTS would read
    either aloud to the listeners."""
    found = [f"latin:{w}" for w in _LATIN_WORD.findall(text)]
    found += [f"loop:{m.group(1)}" for m in _LOOP.finditer(text)]
    return found


# Days counted with 天 (第二天, 三天) are Mandarin; spoken Cantonese says 日.
_MANDARIN_DAYS = re.compile(
    r"(?:第[一二三四五六七八九十兩两幾几\d]+|[一二三四五六七八九十兩两幾几\d]+)天"
)


def mandarin_words(text: str, words: list[str]) -> list[str]:
    """Mandarin words left in Cantonese output (今天, 您, 他們, 很 ...) plus days counted with
    天. The Cantonese voice reads them aloud, and they sound wrong to the listeners."""
    found = [m.group() for m in _MANDARIN_DAYS.finditer(text)]
    for word in sorted(words, key=len, reverse=True):
        found += [word] * text.count(word)
        text = text.replace(word, "\0")
    return found


def added_time_words(source: str, text: str, time_words: dict[str, list[str]]) -> list[str]:
    """Cantonese time words the guide never said, e.g. 聽日 ("tomorrow") when the source has
    no 明天. `time_words` maps each Cantonese word to the Mandarin words that justify it.
    A changed day or time could send the family to the wrong place."""
    source = _to_simplified.convert(source)
    return [
        word
        for word, cues in time_words.items()
        if word in text and not any(cue in source for cue in cues)
    ]


def simplified_chars(text: str) -> list[str]:
    """Characters that only exist in Simplified form (they change under Simplified→Traditional).
    Heuristic: a few characters valid in both scripts (e.g. 后) are also flagged."""
    return [ch for ch in text if _to_traditional.convert(ch) != ch]


def glossary_hits(source: str, output: str, glossary: list[dict], field: str) -> dict:
    """For glossary terms the source mentions, how many appear correctly in the output."""
    source_simplified = _to_simplified.convert(source)
    expected = [t for t in glossary if t["zh"] in source_simplified]
    found = [t for t in expected if t[field].lower() in output.lower()]
    return {
        "expected": len(expected),
        "found": len(found),
        "missing": [t[field] for t in expected if t not in found],
    }


def parse_json_object(text: str) -> dict | None:
    """Pull the first JSON object out of a model reply (tolerates code fences or chatter)."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None
