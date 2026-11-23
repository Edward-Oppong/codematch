"""Tests for CLV (Closing Line Value) analysis in app.analysis.settle."""
import math
import sqlite3
from unittest.mock import MagicMock

import pytest

from app.analysis.settle import clv_analysis


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bet(code, stake, payout=None, status="running"):
    return {"code": code, "stake": stake, "payout": payout, "status": status}


def _mock_con(closing_odds_map):
    """Return a mock sqlite3 connection whose execute().fetchone() returns
    rows looked up by (event_id, label) → closing_odds, or None."""
    con = MagicMock()

    def _execute(sql, params=None, **kw):
        result = MagicMock()
        if params and closing_odds_map is not None:
            key = (params[0], params[1])
            odds = closing_odds_map.get(key)
            result.fetchone.return_value = (odds,) if odds is not None else None
        else:
            result.fetchone.return_value = None
        return result

    con.execute.side_effect = _execute
    return con


def _legs(code, selections):
    """Build a list of leg dicts.  selections = [(event_id, market, pick, odds)]."""
    return [
        {"code": code, "event_id": eid, "market": mkt,
         "pick": pk, "odds": odds}
        for eid, mkt, pk, odds in selections
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_clv_empty():
    result = clv_analysis([], {}, None)
    assert result["n"] == 0
    assert result["beat"] == 0
    assert result["avg_clv"] == 0.0
    assert result["items"] == []


def test_clv_beat_closing_line():
    """Placed at 2.20 > closing 2.00 → positive CLV, beat=1."""
    eid = 123
    bets = [_bet("ABC123", 10, payout=22.0, status="won")]
    legs_by_code = {"ABC123": _legs("ABC123", [(eid, "1X2", "Home", 2.20)])}
    con = _mock_con({(eid, "1X2: Home"): 2.00})

    result = clv_analysis(bets, legs_by_code, con)

    assert result["n"] == 1
    assert result["beat"] == 1
    assert result["beat_pct"] == pytest.approx(100.0)
    assert result["avg_clv"] > 0, "placed 2.20 > closing 2.00 → positive CLV"
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["code"] == "ABC123"
    assert item["placed_odds"] == pytest.approx(2.20, abs=0.01)
    assert item["closing_odds"] == pytest.approx(2.00, abs=0.01)
    assert item["clv_pct"] > 0
    assert item["beat"] is True


def test_clv_lost_closing_line():
    """Placed at 1.80 < closing 2.10 → negative CLV, beat=0."""
    eid = 456
    bets = [_bet("XYZ999", 10, payout=0, status="lost")]
    legs_by_code = {"XYZ999": _legs("XYZ999", [(eid, "1X2", "Away", 1.80)])}
    con = _mock_con({(eid, "1X2: Away"): 2.10})

    result = clv_analysis(bets, legs_by_code, con)

    assert result["n"] == 1
    assert result["beat"] == 0
    assert result["avg_clv"] < 0
    item = result["items"][0]
    assert item["beat"] is False


def test_clv_no_closing_data_falls_back_to_placed():
    """When DB returns nothing, closing odds = placed odds → CLV = 0, not skipped."""
    eid = 789
    bets = [_bet("NOCLOSE", 10)]
    legs_by_code = {"NOCLOSE": _legs("NOCLOSE", [(eid, "1X2", "Draw", 3.50)])}
    # con returns None for every query → falls back to placed odds
    con = _mock_con({})

    result = clv_analysis(bets, legs_by_code, con)
    # CLV = (3.50/3.50) - 1 = 0 → item is included, not beaten
    assert result["n"] == 1
    assert result["beat"] == 0
    assert result["avg_clv"] == pytest.approx(0.0, abs=0.01)


def test_clv_realized_pnl():
    """Realized P&L = sum of (payout - stake) across settled bets."""
    eid1, eid2 = 10, 20
    bets = [
        _bet("WIN1", 10, payout=25, status="won"),
        _bet("LOSE1", 5, payout=0, status="lost"),
    ]
    legs_by_code = {
        "WIN1":  _legs("WIN1",  [(eid1, "1X2", "Home", 2.50)]),
        "LOSE1": _legs("LOSE1", [(eid2, "1X2", "Away", 1.90)]),
    }
    con = _mock_con({
        (eid1, "1X2: Home"): 2.30,
        (eid2, "1X2: Away"): 2.00,
    })

    result = clv_analysis(bets, legs_by_code, con)

    assert result["n"] == 2
    # (25-10) + (0-5) = +10
    assert result["realized_pnl"] == pytest.approx(10.0, abs=0.01)


def test_clv_accumulator_multiplies_legs():
    """Multi-leg bet: placed_odds = product, closing_odds = product of closings."""
    eid1, eid2 = 100, 200
    placed = [
        (eid1, "1X2", "Home", 2.0),
        (eid2, "1X2", "Away", 1.5),
    ]
    # Combined placed = 3.0, combined closing = 2.8
    bets = [_bet("ACCA1", 5)]
    legs_by_code = {"ACCA1": _legs("ACCA1", placed)}
    con = _mock_con({
        (eid1, "1X2: Home"): 1.9,
        (eid2, "1X2: Away"): 1.47,
    })

    result = clv_analysis(bets, legs_by_code, con)

    assert result["n"] == 1
    item = result["items"][0]
    assert item["placed_odds"] == pytest.approx(3.0, abs=0.01)
    assert item["closing_odds"] == pytest.approx(1.9 * 1.47, abs=0.01)
