"""Tests for Phase 7: Accumulator Toxicity Score and Code Surgeon."""
import pytest
from app.analysis import codes as review


def test_toxicity_grade_single_high_return():
    # 1 leg with 0.95 return should be Grade A
    legs = [{"event_id": "e1", "league": "L1", "market": "1X2", "pick": "Home", "odds": 2.0, "prob": 0.475, "ret": 0.95}]
    s = review.summarise(legs)
    assert s["toxicity_grade"] == "A"
    assert s["toxicity_margin_pct"] == pytest.approx(5.0, abs=0.1)
    assert s["breakeven_beat_pct"] < 6.0


def test_toxicity_grade_multi_leg_compounding():
    # 5 legs with 0.93 return each -> 0.93^5 = 0.695 (Grade C)
    legs = [
        {"event_id": f"e{i}", "league": "L1", "market": "1X2", "pick": "Home", "odds": 1.5, "prob": 0.62, "ret": 0.93}
        for i in range(5)
    ]
    s = review.summarise(legs)
    assert s["toxicity_grade"] == "C"
    assert 30.0 < s["toxicity_margin_pct"] < 31.0
    assert s["breakeven_beat_pct"] > 40.0


def test_toxicity_grade_heavy_acca():
    # 15 legs with 0.92 return each -> 0.92^15 = 0.286 (Grade F)
    legs = [
        {"event_id": f"e{i}", "league": "L1", "market": "1X2", "pick": "Home", "odds": 1.4, "prob": 0.65, "ret": 0.92}
        for i in range(15)
    ]
    s = review.summarise(legs)
    assert s["toxicity_grade"] == "F"
    assert s["toxicity_margin_pct"] > 70.0
    assert s["breakeven_beat_pct"] > 200.0


def test_toxic_legs_identified():
    legs = [
        {"event_id": "e1", "league": "L1", "market": "1X2", "pick": "Home", "odds": 2.0, "prob": 0.48, "ret": 0.96}, # healthy
        {"event_id": "e2", "league": "L1", "market": "1X2", "pick": "Home", "odds": 2.0, "prob": 0.43, "ret": 0.86}, # toxic
    ]
    s = review.summarise(legs)
    assert len(s["toxic_legs"]) == 1
    assert s["toxic_legs"][0]["event_id"] == "e2"
