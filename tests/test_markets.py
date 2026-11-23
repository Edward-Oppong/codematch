from app.analysis import markets, picks
from app.analysis.alternatives import alternatives, consistency_check


def test_families_modelled(arsenal):
    counts = {f: len(markets.build_priced(arsenal, f)) for f in markets.MAIN_FAMILIES}
    assert counts == {"goals": 796, "bookings": 95, "corners": 99}
    stats = {f: len(markets.build_priced(arsenal, f)) for f in markets.STAT_FAMILIES}
    assert stats["shots"] == 45 and stats["throw-ins"] == 31 and all(stats.values())
    assert all(markets.families_present(arsenal).values())


def test_no_pick_pays_more_than_it_costs(arsenal):
    """The bookmaker's margin: odds x probability stays below 1 for every pick in this game."""
    assert max(v["ret"] for v in markets.priced_all(arsenal).values()) < 1


def test_safer_and_riskier(arsenal):
    goals = markets.build_priced(arsenal, "goals")
    safer, riskier = alternatives(goals, "Home Total: Over 1.5")
    # equivalent picks (same results) are shown once, as the best-priced one, so compare by outcome
    same = lambda label, lst: any(v["win"] == goals[label]["win"] and v["push"] == goals[label]["push"] for _, v in lst)
    assert same("Home Total: Over 0.5", safer)              # Arsenal 1+ whenever Arsenal 2+
    assert same("Total: Over 1.5", safer)                   # 2+ goals in the game whenever Arsenal score 2
    assert same("Home Total: Over 2.5", riskier)
    for _, v in safer:                                       # every safer pick is at least as likely
        assert v["prob"] >= goals["Home Total: Over 1.5"]["prob"] - 0.01


def test_relation_between_picks():
    a = markets.leg_info("19", "total=1.5", "Over 1.5")      # home over 1.5
    b = markets.leg_info("18", "total=1.5", "Over 1.5")      # total over 1.5
    c = markets.leg_info("18", "total=1.5", "Under 1.5")
    assert markets.relation(a, b) == "b_covers_a"
    assert markets.relation(a, c) == "conflict"
    assert markets.relation(a, markets.leg_info("139", "total=1.5", "Over 1.5")) == "unrelated"


def test_prices_agree_with_the_model(arsenal):
    """Whenever the model says A only wins where B wins, SportyBet prices B at least as likely. This checks the
    half-time readings and refund maths against the bookmaker's own numbers."""
    for fam in markets.FAMILIES:
        assert consistency_check(markets.build_priced(arsenal, fam), tol=0.02) == []


def test_draw_no_bet(arsenal):
    g = markets.build_priced(arsenal, "goals")
    dnb, win = g["Draw No Bet: Home"], g["1X2: Home"]
    assert abs(dnb["prob"] - win["prob"]) < 0.005          # wins exactly when Arsenal win
    assert abs(dnb["push_prob"] - g["1X2: Draw"]["prob"]) < 1e-9
    assert markets.covers(dnb, win) and not markets.covers(win, dnb)
    assert 0.9 < dnb["ret"] < 1


def test_whole_lines_refund(arsenal):
    g = markets.build_priced(arsenal, "goals")
    over1 = g["Total: Over 1"]
    assert over1["push"] and over1["push_prob"] > 0
    assert markets.covers(over1, g["Total: Over 1.5"])
    assert not [k for k, v in g.items() if v.get("cond")]   # every refund chance found in the game's prices


def test_half_time_markets(arsenal):
    g = markets.build_priced(arsenal, "goals")
    assert markets.covers(g["1X2: Home"], g["HT/FT: Home/Home"])
    assert markets.covers(g["1X2: Home"], g["Home Win Both Halves: Yes"])
    assert markets.covers(g["Home Win Either Half: Yes"], g["Home Win Both Halves: Yes"])
    assert markets.covers(g["1H Total: Over 0.5"], g["1H Total: Over 1.5"])
    assert markets.covers(g["Total: Over 0.5"], g["1H Total: Over 0.5"])
    names = ("Arsenal", "Leeds United")
    leg = markets.leg_info("820", "", "Arsenal/Arsenal & 2", names)
    assert leg and markets.relation(leg, markets.leg_info("47", "", "Home/Home", names)) == "b_covers_a"


def test_zones():
    assert [picks.zone(o) for o in (1.03, 1.10, 1.49, 1.50, 1.99, 2.00, 7.5)] == \
        ["vlow", "low", "low", "medium", "medium", "high", "high"]


def test_running_accumulator_compounds():
    rows = picks.with_running_accumulator([{"odds": 1.12, "prob": 0.87} for _ in range(5)])
    assert abs(rows[-1]["acc_prob"] - 0.87 ** 5) < 1e-9
    assert rows[-1]["acc_ret"] < rows[0]["acc_ret"] < 1


def test_best_pick_respects_zone(arsenal):
    lo, hi = picks.zone_range("medium")
    bp = picks.best_pick(arsenal, ["goals"], 0, 1, lo, hi, "prob")
    assert 1.5 <= bp["odds"] < 2.0 and bp["zone"] == "medium"
