import importlib

score_mod = importlib.import_module("05_translate_score")

CFG = {
    "llm": {
        "configs": {
            "gem-min": {"model": "g", "params": {"reasoning_effort": "minimal"}},
            "gem-low": {"model": "g", "params": {"reasoning_effort": "low"}},
            "q-t0.2": {"model": "q", "params": {"reasoning_effort": "none"}},
            "q-t0.7": {"model": "q", "params": {"reasoning_effort": "none"}},
        }
    }
}


def s(ratio, total=0.5, simplified=0):
    return {"ratio": ratio, "total": total, "simplified": simplified}


def test_best_temperature_wins_without_margin():
    scores = {"q-t0.2": s(0.80), "q-t0.7": s(0.82)}
    assert score_mod.pick_setting(["q-t0.2", "q-t0.7"], scores, CFG, 0.05) == "q-t0.7"


def test_lowest_reasoning_kept_unless_clearly_worse():
    close = {"gem-min": s(0.80), "gem-low": s(0.83)}
    assert score_mod.pick_setting(["gem-min", "gem-low"], close, CFG, 0.05) == "gem-min"
    far = {"gem-min": s(0.70), "gem-low": s(0.85)}
    assert score_mod.pick_setting(["gem-min", "gem-low"], far, CFG, 0.05) == "gem-low"
