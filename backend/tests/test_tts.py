import pytest

from app.providers.base import SpeechFailed
from app.providers.tts import GoogleTts, split_in_two

CFG = {
    "endpoint": "texttospeech.googleapis.com",
    "language": "yue-HK",
    "voices": ["yue-HK-Chirp3-HD-Despina", "yue-HK-Standard-A"],
}
DESPINA, STANDARD = CFG["voices"]
LONG = "一個本地地陪，可以將江景講得好清楚，亦都識得避開樓梯，同埋避開大霧天氣。"  # 36 characters


class TooLong(Exception):
    """Google's InvalidArgument for an over-long sentence."""

    code = 400

    def __init__(self):
        super().__init__("400 This request contains sentences that are too long.")


class Refused(Exception):
    code = 400  # a 400 for some other reason: not split


class FakeTts(GoogleTts):
    """Despina refuses text longer than `limit` characters; `failing` voices always fail."""

    def __init__(self, failing: set[str] = frozenset(), limit: int = 1000, other_400=False):
        super().__init__(CFG)
        self.failing, self.limit, self.other_400 = failing, limit, other_400
        self.tried: list[tuple[str, str]] = []

    async def _synthesize(self, text, voice):
        self.tried.append((voice, text))
        if voice in self.failing:
            raise RuntimeError("voice unavailable")
        if voice == DESPINA and len(text) > self.limit:
            raise Refused() if self.other_400 else TooLong()
        return f"[{text}]".encode()


async def test_main_voice():
    speech = await FakeTts().speak("你好")
    assert (speech.voice, speech.audio, speech.attempts, speech.pieces) == (
        DESPINA,
        "[你好]".encode(),
        [],
        1,
    )


async def test_falls_back_to_the_older_voice():
    tts = FakeTts({DESPINA})
    speech = await tts.speak("你好")
    assert speech.voice == STANDARD
    assert [(a.provider, a.outcome) for a in speech.attempts] == [(DESPINA, "error")]


async def test_every_voice_fails():
    with pytest.raises(SpeechFailed):
        await FakeTts(set(CFG["voices"])).speak("你好")


async def test_a_sentence_too_long_for_despina_is_split_and_joined_into_one_clip():
    speech = await FakeTts(limit=20).speak(LONG)
    assert (speech.voice, speech.pieces, speech.attempts) == (DESPINA, 2, [])
    first, second = "一個本地地陪，可以將江景講得好清楚，", "亦都識得避開樓梯，同埋避開大霧天氣。"
    assert speech.audio == f"[{first}][{second}]".encode()  # in order, every word kept


async def test_split_again_until_each_piece_is_short_enough():
    speech = await FakeTts(limit=12).speak(LONG)  # 18 + 18 characters -> 7, 11, 9, 9
    assert speech.voice == DESPINA and speech.pieces == 4
    assert speech.audio.decode().replace("][", "").strip("[]") == LONG


async def test_a_long_sentence_without_commas_goes_to_the_older_voice():
    speech = await FakeTts(limit=5).speak("一二三四五六七八九十。")
    assert speech.voice == STANDARD
    assert [(a.provider, a.outcome) for a in speech.attempts] == [(DESPINA, "rejected")]


async def test_another_refusal_is_not_split():
    tts = FakeTts(limit=20, other_400=True)
    speech = await tts.speak(LONG)
    assert speech.voice == STANDARD
    assert [voice for voice, _ in tts.tried] == [DESPINA, STANDARD]


def test_split_at_the_mark_nearest_the_middle():
    assert split_in_two("甲乙丙，丁，戊己庚辛壬。") == ("甲乙丙，丁，", "戊己庚辛壬。")
    assert split_in_two("甲、乙、丙、丁。") == ("甲、乙、", "丙、丁。")
    assert split_in_two("沒有標點的句子。") is None
    assert split_in_two("，開頭的逗號不算。") is None
