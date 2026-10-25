import pytest

from app.providers.base import SpeechFailed
from app.providers.tts import GoogleTts

CFG = {
    "endpoint": "texttospeech.googleapis.com",
    "language": "yue-HK",
    "voices": ["yue-HK-Chirp3-HD-Despina", "yue-HK-Standard-A"],
}


class FakeTts(GoogleTts):
    def __init__(self, failing: set[str]):
        super().__init__(CFG)
        self.failing = failing
        self.tried: list[str] = []

    async def _synthesize(self, text, voice):
        self.tried.append(voice)
        if voice in self.failing:
            raise RuntimeError("voice unavailable")
        return b"ID3 mp3"


async def test_main_voice():
    speech = await FakeTts(set()).speak("你好")
    assert (speech.voice, speech.audio, speech.attempts) == (
        "yue-HK-Chirp3-HD-Despina",
        b"ID3 mp3",
        [],
    )


async def test_falls_back_to_the_older_voice():
    tts = FakeTts({"yue-HK-Chirp3-HD-Despina"})
    speech = await tts.speak("你好")
    assert speech.voice == "yue-HK-Standard-A"
    assert [(a.provider, a.outcome) for a in speech.attempts] == [
        ("yue-HK-Chirp3-HD-Despina", "error")
    ]


async def test_every_voice_fails():
    with pytest.raises(SpeechFailed):
        await FakeTts(set(CFG["voices"])).speak("你好")
