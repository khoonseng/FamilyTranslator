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


def test_cantonese_char_count():
    chars = ["哋", "唔", "喺", "嘅", "咗", "冇", "佢"]
    assert scoring.cantonese_char_count("我哋而家去食重庆火锅,你哋想唔想食辣啲?", chars) == 3
    assert scoring.cantonese_char_count("大家好,我们现在到了洪崖洞。", chars) == 0


def test_cantonese_share_per_sentence():
    chars = ["哋", "唔", "喺", "嘅", "咗", "冇", "佢", "乜", "咩"]
    # A Cantonese remark misheard by Chirp 3 (佢 -> 渠) still scores high.
    assert scoring.cantonese_share("渠讲乜呀?我哋几点食饭?", chars) == pytest.approx(2 / 10)
    # A guide sentence with one stray Cantonese character scores low.
    guide = "等一下我们坐长江索道过江，排队可能要四十分钟左右，唔"
    assert scoring.cantonese_share(guide, chars) < 0.05
    assert scoring.cantonese_share("。", chars) == 0.0


def test_glitches():
    assert scoring.glitches("排隊可能要四十 processing 分鐘左右") == ["latin:processing"]
    assert scoring.glitches("聽住，聽住，聽住，聽住，明天去武隆") == ["loop:聽住，"]
    assert scoring.glitches("大家早晨，我哋第一站先去解放碑。") == []
    # Ordinary doubling in Cantonese is not a loop.
    assert scoring.glitches("佢慢慢行，好好睇吓。") == []


@pytest.mark.parametrize(
    "n, words",
    [
        (0, "零"),
        (5, "五"),
        (10, "十"),
        (15, "十五"),
        (40, "四十"),
        (105, "一百零五"),
        (2026, "二千零二十六"),
    ],
)
def test_chinese_number(n, words):
    assert scoring.chinese_number(n) == words


def test_cer_treats_digits_and_chinese_numerals_alike():
    assert scoring.cer("建议5到6天只玩重庆", "建议五到六天只玩重庆") == 0.0
    assert scoring.cer("大概40分钟", "大概四十分钟") == 0.0
