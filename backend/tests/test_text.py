import pytest

from app import config
from app.pipeline.bubbles import Bubbles
from app.pipeline.text import cantonese_share, drop_reason, split_sentences

PIPE = config.load()["pipeline"]


def test_split_keeps_punctuation_and_closing_quotes():
    assert split_sentences("他说：「到了。」我们走吧！好吗？") == [
        "他说：「到了。」",
        "我们走吧！",
        "好吗？",
    ]


def test_split_does_not_cut_decimals_and_keeps_an_unfinished_tail():
    assert split_sentences("大概3.5公里。然后") == ["大概3.5公里。", "然后"]


@pytest.mark.parametrize(
    "sentence, reason",
    [
        ("我哋喺度等緊佢哋。", "cantonese"),  # family chatter
        ("嗯。", "filler"),
        ("嗯嗯啊。", "filler"),
        ("好", "short"),
        ("大家跟紧我，不要走散了。", None),  # the guide
        ("这个地方唔，人很多，大家要注意安全，不要走散了。", None),  # one stray 唔 survives
    ],
)
def test_junk_filter(sentence, reason):
    assert drop_reason(sentence, PIPE) == reason


def test_cantonese_share():
    assert cantonese_share("大家跟紧我。", PIPE["cantonese_only_chars"]) == 0
    assert cantonese_share("佢哋喺度。", PIPE["cantonese_only_chars"]) == 0.75


def test_bubble_caps_on_audio():
    bubbles = Bubbles(pause_s=2.0, max_audio_s=45, max_sentences=6)
    first = bubbles.on_segment(pause_s=0)
    bubbles.add_audio(first, 45)
    assert bubbles.on_segment(pause_s=0.5) != first
