"""Tests for Phase 5: Personal Calibration Engine & Significance Gate."""
import pytest
from app.analysis import calibrate as calib


def test_wilson_ci_bounds():
    # 0 observations returns (0, 1)
    assert calib.wilson_ci(0, 0) == (0.0, 1.0)

    # 100 out of 100 wins should have lower bound close to 1
    low, high = calib.wilson_ci(100, 100)
    assert low > 0.95
    assert high <= 1.0

    # 50 out of 100 should be centred around 0.5
    low, high = calib.wilson_ci(100, 50)
    assert 0.39 < low < 0.42
    assert 0.58 < high < 0.61


def test_significance_verdict():
    # Not enough data (< 50)
    v1 = calib.significance_verdict(20, 15, 0.60)
    assert v1["tier"] == "not_enough"
    assert "Need 30 more bets" in v1["message"]

    # Early signal (50 <= n < 200)
    v2 = calib.significance_verdict(80, 50, 0.60)
    assert v2["tier"] == "early"
    assert v2["n"] == 80

    # Confident verdict with significant positive edge
    # e.g. 200 bets, 160 wins (80%) vs 60% stated
    v3 = calib.significance_verdict(200, 160, 0.60)
    assert v3["tier"] == "confident"
    assert v3["significant"] is True
    assert v3["edge_pct"] > 0
    assert "beat SportyBet" in v3["message"]

    # Confident verdict with negative edge
    v4 = calib.significance_verdict(200, 80, 0.60)
    assert v4["tier"] == "confident"
    assert v4["significant"] is True
    assert v4["edge_pct"] < 0
    assert "underperform" in v4["message"]


def test_market_edge_and_family_mapping():
    legs = [
        {"market": "1X2", "prob": 0.5, "status": "won", "sel_key": "k1"},
        {"market": "1X2", "prob": 0.5, "status": "lost", "sel_key": "k2"},
        {"market": "Over/Under 2.5", "prob": 0.6, "status": "won", "sel_key": "k3"},
        {"market": "Corners Total Over 9.5", "prob": 0.55, "status": "won", "sel_key": "k4"},
        {"market": "Corners Total Over 9.5", "prob": 0.55, "status": "won", "sel_key": "k4"}, # duplicate sel_key
        {"market": "Booking 1st Half", "prob": 0.4, "status": "void", "sel_key": "k5"}, # void ignored
        {"market": "Handicap 0:2", "prob": 0.8, "status": "won", "sel_key": "k6"},
        {"market": "GG/NG", "prob": 0.52, "status": "lost", "sel_key": "k7"},
        {"market": "1st Half - Over/Under 0.5", "prob": 0.7, "status": "won", "sel_key": "k8"},
        {"market": "Double Chance - 1UP", "prob": 0.65, "status": "won", "sel_key": "k9"},
        {"market": "Anytime Goalscorer", "prob": 0.35, "status": "won", "sel_key": "k10"},
        {"market": "Goalkeeper Saves Over/Under", "prob": 0.58, "status": "won", "sel_key": "k11"},
    ]
    edges = calib.market_edge(legs)
    families = {e["family"] for e in edges}
    assert "1X2 & Match Result" in families
    assert "Totals & Over/Under" in families
    assert "Corners" in families
    assert "Handicap" in families
    assert "Both Teams to Score (GG/NG)" in families
    assert "Half-Time & Halves" in families
    assert "Double Chance & Draw No Bet" in families
    assert "Player Props (Goalscorer/Shots)" in families
    assert "Goalkeeper & Saves" in families
    assert "Bookings" not in families  # void only

    corner_edge = next(e for e in edges if e["family"] == "Corners")
    assert corner_edge["n"] == 1  # de-duplicated k4
    assert corner_edge["wins"] == 1

    handicap_edge = next(e for e in edges if e["family"] == "Handicap")
    assert handicap_edge["wins"] == 1


def test_calibrated_prob_fallback_and_blend():
    legs = []
    # With fewer than MIN_BETS_FOR_CALIBRATION, returns stated prob unchanged
    assert calib.calibrated_prob("1X2", 0.60, legs) == 0.60

    # Create 60 winning legs around 0.60 prob for 1X2
    for i in range(60):
        legs.append({
            "market": "1X2",
            "prob": 0.62,
            "status": "won" if i < 45 else "lost", # 45/60 = 75% win rate
            "sel_key": f"key_{i}",
        })
    calibrated = calib.calibrated_prob("1X2", 0.60, legs)
    # empirical 0.75, stated 0.60, blended 0.7*0.75 + 0.3*0.60 = 0.525 + 0.18 = 0.705
    assert calibrated > 0.60
    assert calibrated < 0.75


def test_kelly_tier():
    assert calib.kelly_tier([]) == "flat"
    legs_50 = [{"status": "won", "sel_key": f"s_{i}"} for i in range(55)]
    assert calib.kelly_tier(legs_50) == "calibrated"
    legs_210 = [{"status": "won", "sel_key": f"s_{i}"} for i in range(210)]
    assert calib.kelly_tier(legs_210) == "ready"


def test_results_route_renders_calibration(client):
    rv = client.get("/results/")
    assert rv.status_code == 200
    page = rv.data.decode()
    assert "Personal Calibration &amp; Empirical Edge" in page or "Personal Calibration & Empirical Edge" in page
