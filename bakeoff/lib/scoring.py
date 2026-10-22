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


def normalize(text: str, script: str = "simplified") -> str:
    """Punctuation-free, lower-cased text in one Chinese script, for a fair comparison."""
    text = strip_punct(text).lower()
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
