import pytest

from lib.records import median, percentile
from lib.stt import SttResult
from lib.text import split_sentences


def test_split_sentences_chinese():
    text = "大家好。我们现在到了洪崖洞！晚上七点开灯，人很多？"
    assert split_sentences(text) == ["大家好。", "我们现在到了洪崖洞！", "晚上七点开灯，人很多？"]


def test_split_sentences_keeps_unfinished_tail():
    # A chunk cut by a pause can end mid-sentence; the tail is still translated.
    assert split_sentences("先去解放碑。然后我们") == ["先去解放碑。", "然后我们"]


def test_split_sentences_english_and_quotes():
    text = "Can we stop soon? I need the toilet. 佢話「好呀。」然後走咗"
    assert split_sentences(text) == [
        "Can we stop soon?",
        "I need the toilet.",
        "佢話「好呀。」",
        "然後走咗",
    ]


def test_labelled_cantonese_by_majority_of_characters():
    mostly_yue = SttResult("", 0.1, [("我哋而家去食飯啦", "yue-Hant-HK"), ("好", "cmn-Hans-CN")])
    assert mostly_yue.labelled_cantonese()
    mostly_cmn = SttResult("", 0.1, [("嗯", "yue-hant-hk"), ("我们现在去洪崖洞", "cmn-Hans-CN")])
    assert not mostly_cmn.labelled_cantonese()
    assert not SttResult("", 0.1, []).labelled_cantonese()


def test_median_and_percentile_ignore_missing():
    assert median([3, None, 1, 2]) == 2
    assert median([1, 2, 3, 4]) == 2.5
    assert median([None]) is None
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 90) == 9
    assert percentile([], 90) is None


@pytest.mark.parametrize("text", ["", "   "])
def test_split_sentences_empty(text):
    assert split_sentences(text) == []
