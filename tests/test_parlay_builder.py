"""Unit and integration tests for Custom Parlay Builder."""
import json
import pytest
from app.analysis import parlay_builder
from conftest import future, make_league, upload


def _mock_games():
    """Create a list of game candidates with odds, probabilities, and kick-off times."""
    base_time = 1795000000000
    games = []
    # 6 matches, each 2 hours apart
    for i in range(6):
        start_ms = base_time + (i * 2 * 3600 * 1000)
        cands = [
            {"event_id": f"sr:match:10{i}", "match": f"Team A{i} v Team B{i}", "label": "Over 1.5",
             "odds": 1.25, "prob": 0.80, "ret": 1.0, "start_ms": start_ms, "sel": {"eventId": f"sr:match:10{i}"}},
            {"event_id": f"sr:match:10{i}", "match": f"Team A{i} v Team B{i}", "label": "Home Win",
             "odds": 1.60, "prob": 0.60, "ret": 0.96, "start_ms": start_ms, "sel": {"eventId": f"sr:match:10{i}"}},
            {"event_id": f"sr:match:10{i}", "match": f"Team A{i} v Team B{i}", "label": "Both Teams to Score",
             "odds": 1.95, "prob": 0.50, "ret": 0.975, "start_ms": start_ms, "sel": {"eventId": f"sr:match:10{i}"}},
        ]
        games.append(cands)
    return games


def test_build_target_odds():
    games = _mock_games()
    res = parlay_builder.build_target_odds(games, target_odds=3.0, min_legs=2, max_legs=5)
    assert res["strategy"] == "target_odds"
    assert len(res["legs"]) >= 2
    assert res["totals"]["odds"] >= 2.98
    assert res["reached"] is True


def test_build_time_staggered():
    games = _mock_games()
    res = parlay_builder.build_time_staggered(games, n_legs=3, min_gap_mins=100)
    assert res["strategy"] == "time_staggered"
    assert len(res["legs"]) == 3
    # Check that each leg is strictly after the previous leg + gap
    gap_ms = 100 * 60 * 1000
    for idx in range(1, len(res["legs"])):
        assert res["legs"][idx]["start_ms"] >= res["legs"][idx - 1]["start_ms"] + gap_ms
    assert len(res["timeline"]) == 3
    assert res["timeline"][-1]["is_final"] is True


def test_build_zone_structured():
    games = _mock_games()
    # Test High-Chance Double
    res = parlay_builder.build_zone_structured(games, preset_key="high_chance_double")
    assert res["strategy"] == "zone_structured"
    assert len(res["legs"]) == 2
    assert res["satisfied"] is True

    # Test Anchor + Engine
    res_ae = parlay_builder.build_zone_structured(games, preset_key="anchor_engine")
    assert res_ae["strategy"] == "zone_structured"
    assert len(res_ae["legs"]) > 0


def test_build_round_robin():
    games = _mock_games()
    # 4 matches, doubles (2-folds) -> 6 combinations
    res = parlay_builder.build_round_robin(games, pool_size=4, fold_size=2, unit_stake=10.0)
    assert res["strategy"] == "round_robin"
    assert res["pool_size"] == 4
    assert res["fold_size"] == 2
    assert res["n_combinations"] == 6
    assert res["total_staked"] == 60.0
    assert len(res["combinations"]) == 6
    assert len(res["scenarios"]) == 3  # wins: 2, 3, 4


def test_parlay_page_renders_all_strategies(client, arsenal):
    ev = future(arsenal)
    upload(client, json.dumps(make_league([ev])))

    for strat in ["target", "staggered", "zone", "round_robin"]:
        res = client.get(f"/leagues/parlay?strat={strat}")
        assert res.status_code == 200
        page = res.get_data(as_text=True)
        assert "Custom Parlay Builder" in page
        assert "Get Leagues" in page
