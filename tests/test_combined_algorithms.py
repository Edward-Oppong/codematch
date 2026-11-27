"""Tests for the 4 combined quantitative algorithms:
1. Implied Poisson Goal Model (app/analysis/poisson.py)
2. Calibration Adjustments (app/analysis/calibrate.py)
3. Steam + Value Combo (store.steam_map & /leagues/singles?by=sharp)
4. Multi-Code Consensus + Value Filter (store.consensus_counts & /codes/fixtures)
"""
import time

from app import store
from app.analysis import calibrate, poisson
from app.db import get_db


def test_poisson_fit_and_edge():
    # Home favorite (~55% H, 24% D, 21% A) and ~58% Over 2.5
    picks_list = [
        {"label": "1X2: Home", "prob": 0.55},
        {"label": "1X2: Draw", "prob": 0.24},
        {"label": "1X2: Away", "prob": 0.21},
        {"label": "Total: Over 2.5", "prob": 0.58},
    ]
    fit = poisson.fit_event(picks_list)
    assert fit is not None
    assert fit["lh"] > fit["la"]
    assert 2.4 <= fit["total_xg"] <= 3.3
    assert fit["fit_err"] < 0.01

    p_btts = poisson.model_prob(fit, "Both Teams to Score: Yes")
    assert p_btts is not None and 0.4 <= p_btts <= 0.75

    p_o15 = poisson.model_prob(fit, "Total: Over 1.5")
    assert p_o15 is not None and p_o15 > 0.65

    # Ignores non-FT markets
    assert poisson.model_prob(fit, "1st Half - Total: Over 1.5") is None
    assert poisson.model_prob(fit, "Corners: Over 9.5") is None

    # Positive edge if SportyBet posts lower prob than model
    edge = poisson.edge_vs_model(fit, "Total: Over 1.5", p_o15 - 0.05)
    assert edge is not None and edge > 0.04


def test_calibration_adjustments():
    # Below min_n=15 -> empty
    few = [{"market": "1X2", "prob": 0.60, "status": "won", "sel_key": f"k{i}"} for i in range(10)]
    assert calibrate.calibration_adjustments(few) == {}

    # 20 wins out of 20 at 60% stated -> +10% capped positive adjustment
    many = [{"market": "1X2", "prob": 0.60, "status": "won", "sel_key": f"w{i}"} for i in range(20)]
    adj = calibrate.calibration_adjustments(many)
    assert adj["1X2 & Match Result"] == 0.10


def test_steam_consensus_and_singles_sharp_sort(app, client):
    now_ms = int(time.time() * 1000) + 86_400_000
    with app.app_context():
        con = get_db()
        con.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("ev1", "sr:tournament:17", "Premier League", "England", "Arsenal", "Chelsea",
             now_ms, 120, int(time.time()), "{}"),
        )
        # Anchor picks + value pick
        picks_data = [
            ("ev1", "goals", "1X2: Home", 1.85, 0.52, 0.96, 0, 0, 0.0, "", "1", "", "1", "Home", "k1", "main", "1", "1X2", 1, 0.96),
            ("ev1", "goals", "1X2: Draw", 3.60, 0.26, 0.96, 0, 0, 0.0, "", "1", "", "2", "Draw", "k2", "main", "X", "1X2", 1, 0.96),
            ("ev1", "goals", "1X2: Away", 4.20, 0.22, 0.96, 0, 0, 0.0, "", "1", "", "3", "Away", "k3", "main", "2", "1X2", 1, 0.96),
            ("ev1", "goals", "Total: Over 2.5", 1.75, 0.55, 0.96, 0, 0, 0.0, "", "18", "total=2.5", "12", "Over 2.5", "k4", "main", "Over", "Total", 1, 0.96),
        ]
        con.executemany("INSERT INTO picks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", picks_data)
        con.execute("INSERT INTO priced_at VALUES('ev1', ?, 0)", (int(time.time()),))
        # History showing Total: Over 2.5 steamed from 1.90 down to 1.75
        con.execute("INSERT INTO history VALUES('ev1', 'goals', 'Total: Over 2.5', 1.90, 0.51, 1000)")
        # 2 codes sharing Total: Over 2.5 on ev1
        for code in ("C1", "C2"):
            con.execute("INSERT INTO codes VALUES(?, ?, 1, 'hub', 10)", (code, int(time.time())))
            con.execute(
                "INSERT INTO selections VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (code, "sk1", "ev1", "Arsenal v Chelsea", "England Premier League",
                 "Total", "Over 2.5", 1.75, now_ms, "18", "total=2.5", "12", 0.55, "over"),
            )
        con.commit()

        sm = store.steam_map(con, ["ev1"])
        assert sm[("ev1", "Total: Over 2.5")] < -5.0

        cc = store.consensus_counts(con, ["ev1"])
        assert cc[("ev1", "total", "over 2.5")] == 2

    r = client.get("/leagues/singles?by=sharp&dir=no_unders")
    assert r.status_code == 200
    assert b"Steam" in r.data
    assert b"xG" in r.data
    assert b"In 2 codes" in r.data

    r2 = client.get("/codes/fixtures?no_unders=1&minret=90")
    assert r2.status_code == 200
