import pytest

from app import config
from app.usage import Meter

PRICES = config.load()["spending"]


def test_cost_adds_every_kind_of_usage():
    meter = Meter()
    meter.stt("chirp_3", 60)  # 1 minute: US$0.016
    meter.stt("gpt-transcribe", 120)  # 2 minutes: US$0.009
    meter.llm("gemini", 1_000_000, 100_000)  # US$1.50 + US$0.75
    meter.mt(50_000)  # US$1.00
    meter.tts("yue-HK-Chirp3-HD-Despina", 100_000)  # US$3.00
    meter.tts("yue-HK-Standard-A", 250_000)  # US$1.00
    assert meter.cost(PRICES) == pytest.approx(0.016 + 0.009 + 1.50 + 0.75 + 1.00 + 3.00 + 1.00)


def test_unpriced_names_cost_nothing():
    meter = Meter()
    meter.llm("someone-new", 1_000_000, 1_000_000)
    assert meter.cost(PRICES) == 0


def test_counts_round_trip_and_mark_changes():
    meter = Meter()
    assert not meter.changed
    meter.tts("yue-HK-Chirp3-HD-Despina", 12)
    assert meter.changed
    again = Meter(meter.to_dict())
    assert again.to_dict() == {"tts": {"yue-HK-Chirp3-HD-Despina": 12}}
    assert not again.changed
