"""Sentence splitting, as the server will do it: at sentence-ending punctuation (hard rule 9)."""

import re

# A sentence ends at Chinese or Western sentence enders plus any closing quotes, or at a full
# stop followed by a space (so 3.5 is not split). The punctuation stays with its sentence.
_SENTENCE_END = re.compile(r"([。！？!?；;…]+[」』”’\"']*|\.(?=\s))")


def split_sentences(text: str) -> list[str]:
    marked = _SENTENCE_END.sub(r"\1\n", text)
    return [s.strip() for s in marked.split("\n") if s.strip()]
