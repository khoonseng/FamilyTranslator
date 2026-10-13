import pytest

from lib import scoring

SCORING = {
    "colloquial_markers": ["佢", "係", "嘅", "咗", "唔", "喺", "冇", "咩", "啲", "嘢"],
    "formal_markers": [
        "他們",
        "她們",
        "他",
        "她",
        "它",
        "們",
        "的",
        "是",
        "在",
        "沒有",
        "沒",
        "這",
        "那",
        "什麼",
        "怎麼",
        "不",
    ],
    "formal_exceptions": [
        "不過",
        "不同",
        "不少",
        "不錯",
        "不斷",
        "不如",
        "不得了",
        "目的",
        "的士",
        "實在",
        "存在",
    ],
}


def test_cer_perfect_ignores_punctuation_and_script():
    assert scoring.cer("我們到了洪崖洞。", "我们到了洪崖洞") == 0.0


def test_cer_counts_substitution_and_deletion():
    # 解放碑 vs 解放杯 (1 substitution) and a missing 了 (1 deletion) over 6 chars
    assert scoring.cer("我到了解放碑", "我到解放杯") == pytest.approx(2 / 6)


def test_cer_empty_reference():
    assert scoring.cer("", "") == 0.0
    assert scoring.cer("", "嗯") == 1.0


def test_colloquial_sentence_scores_high():
    s = scoring.colloquial_score("佢哋喺度等緊我哋，唔使急。", SCORING)
    assert s == {"colloquial": 3, "formal": 0, "ratio": 1.0}


def test_formal_sentence_scores_low():
    s = scoring.colloquial_score("他們在這裡等我們，不用著急。", SCORING)
    # 他們, 在, 這, 們 (我們), 不 -> 5 formal; 他們 counted once, not as 他 + 們
    assert s["colloquial"] == 0
    assert s["formal"] == 5
    assert s["ratio"] == 0.0


def test_exception_words_are_not_formal():
    s = scoring.colloquial_score("不過佢哋唔同", SCORING)
    assert s["formal"] == 0


def test_no_markers_gives_no_ratio():
    assert scoring.colloquial_score("洪崖洞", SCORING)["ratio"] is None


def test_simplified_chars_detected_in_cantonese_output():
    assert scoring.simplified_chars("佢哋喺重庆") == ["庆"]
    assert scoring.simplified_chars("佢哋喺重慶") == []


def test_glossary_hits():
    glossary = [
        {"zh": "洪崖洞", "yue": "洪崖洞", "en": "Hongyadong"},
        {"zh": "鹅岭二厂", "yue": "鵝嶺二廠", "en": "Eling No. 2 Factory"},
        {"zh": "解放碑", "yue": "解放碑", "en": "Jiefangbei"},
    ]
    source, output = "先去洪崖洞再去鹅岭二厂", "先去洪崖洞，再去鵝嶺二廠"
    hits = scoring.glossary_hits(source, output, glossary, "yue")
    assert hits == {"expected": 2, "found": 2, "missing": []}
    hits = scoring.glossary_hits("先去洪崖洞", "First we go to Hong Ya Cave", glossary, "en")
    assert hits["missing"] == ["Hongyadong"]


@pytest.mark.parametrize(
    "reply",
    [
        '{"yue": "佢喺度", "en": "He is here"}',
        'Sure:\n```json\n{"yue": "佢喺度", "en": "He is here"}\n```',
    ],
)
def test_parse_json_object(reply):
    assert scoring.parse_json_object(reply)["yue"] == "佢喺度"


def test_parse_json_object_rejects_garbage():
    assert scoring.parse_json_object("no json here") is None
    assert scoring.parse_json_object("{not json}") is None
