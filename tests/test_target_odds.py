"""Reach a total odds with the highest chance: checked against trying every combination."""
import itertools
import math
import random

from app.analysis import target


def brute(games, goal):
    best = None
    for choice in itertools.product(*[[None] + g for g in games]):
        legs = [c for c in choice if c]
        if not legs or math.prod(c["odds"] for c in legs) < goal:
            continue
        p = math.prod(c["prob"] for c in legs)
        if best is None or p > best:
            best = p
    return best


def game(rng, n):
    out = []
    for _ in range(n):
        p = rng.uniform(0.2, 0.98)
        margin = rng.uniform(0.85, 0.99)
        out.append({"odds": round(max(1.01, margin / p), 2), "prob": p})
    return out


def test_matches_brute_force():
    rng = random.Random(7)
    for _ in range(60):
        games = [game(rng, rng.randint(1, 4)) for _ in range(rng.randint(1, 5))]
        goal = rng.uniform(1.2, 8)
        want = brute(games, goal * 1.005)     # anything comfortably above the target must be found
        got = target.best_for_odds(games, goal)
        if got is None:
            assert want is None
            continue
        t = target.totals(got)
        assert t["odds"] >= goal * 0.995                 # a hair under at worst, from the rounding
        if want is not None:
            assert t["prob"] >= want - 1e-12


def test_exact_hit_counts():
    legs = target.best_for_odds([[{"odds": 1.25, "prob": 0.76}], [{"odds": 1.6, "prob": 0.58}]], 2.0)
    assert legs and len(legs) == 2


def test_one_pick_per_game():
    games = [[{"odds": 1.5, "prob": 0.62}, {"odds": 1.2, "prob": 0.8}], [{"odds": 1.3, "prob": 0.74}]]
    legs = target.best_for_odds(games, 1.8)
    assert len(legs) == len({id(g) for g in games}) or len(legs) <= 2
    ids = [next(i for i, g in enumerate(games) if l in g) for l in legs]
    assert len(ids) == len(set(ids))


def test_beats_stacking_short_picks():
    # twenty near-certain picks with a 2% margin each, and one ordinary pick with a 7% margin
    short = [[{"odds": 1.04, "prob": 0.98 / 1.04}] for _ in range(20)]
    single = [[{"odds": 1.6, "prob": 0.93 / 1.6}]]
    games = short + single
    best = target.totals(target.best_for_odds(games, 1.5))
    stacked = target.totals(target.stack_safest(games, 1.5))
    assert best["n"] == 1 and stacked["n"] > 5
    assert best["prob"] > stacked["prob"] + 0.05


def test_unreachable():
    assert target.best_for_odds([[{"odds": 1.1, "prob": 0.9}]], 5) is None
    assert target.stack_safest([[{"odds": 1.1, "prob": 0.9}]], 5) is None
    assert target.best_for_odds([], 2) is None


def test_on_real_game(arsenal):
    event = arsenal
    from app.analysis import markets
    cands = target.from_priced(event["eventId"], "Arsenal v Leeds", markets.priced_all(event))
    legs = target.best_for_odds([cands], 1.5)
    assert len(legs) == 1 and legs[0]["odds"] >= 1.5
    # the best single pick at 1.5+ is the most likely pick there is at those odds
    assert legs[0]["prob"] == max(c["prob"] for c in cands if c["odds"] >= 1.5)
    assert all(not c.get("push") for c in cands) and legs[0]["sel"]["marketId"]


def _league(client, arsenal, n=6):
    import json
    from conftest import future, make_league, upload
    games = []
    for i in range(n):
        g = future(arsenal, hours=5 + i)
        g["eventId"], g["homeTeamName"], g["awayTeamName"] = f"sr:match:{700 + i}", f"H{i}", f"A{i}"
        g["sport"]["category"] = {"id": "c", "name": "X", "tournament": {"id": "sr:tournament:17", "name": "PL"}}
        games.append(g)
    upload(client, json.dumps(make_league(games)))
    return games


def _figure(html, label):
    import re
    return float(re.search(re.escape(label) + r'</span><b[^>]*>([\d.]+)%', html).group(1))


def test_leagues_target_odds(client, arsenal):
    _league(client, arsenal)
    html = client.get("/leagues/?zone=any&fam=goals&upcoming=1&todds=3").get_data(as_text=True)
    assert "Highest chance for odds of 3" in html and "Make a SportyBet booking code from these" in html
    best = _figure(html, "Chance this code wins")
    if "Stacking the most likely picks instead" in html:
        assert best >= _figure(html, "Stacking the most likely picks instead")
    # a minimum chance per leg is respected
    html = client.get("/leagues/?zone=any&fam=goals&upcoming=1&todds=3&minp=70").get_data(as_text=True)
    section = html.split("Highest chance for odds of 3")[1].split("One pick per game")[0]
    import re
    chances = [float(x) for x in re.findall(r'data-label="Chance" class="num">([\d.]+)%', section)]
    assert chances and min(chances) >= 70
    html = client.get("/leagues/?zone=low&fam=goals&upcoming=1&todds=5000").get_data(as_text=True)
    assert "reaches odds of 5000" in html


def test_review_same_odds_higher_chance(client, arsenal):
    import json
    from conftest import upload
    from test_fixtures_across_codes import multi_code
    games = _league(client, arsenal, 4)
    legs = [(g, "18", "total=1.5", "Over 1.5") for g in games]
    upload(client, json.dumps(multi_code("ZZZ", legs)))
    page = client.get("/code/ZZZ").get_data(as_text=True)
    assert "Same odds, higher chance" in page
    odds = float(page.split('name="todds" value="')[1].split('"')[0])
    html = client.get(f"/code/ZZZ?todds={odds}").get_data(as_text=True)
    before, after = html.split("Chance of winning</span><b class=\"\">")[1].split("</b>")[0].split(" → ")
    assert float(after.rstrip("%")) >= float(before.rstrip("%"))
    assert "Make a SportyBet booking code from this version" in html


def test_review_minimum_chance_per_leg(client, arsenal):
    import json, re
    from conftest import upload
    from test_fixtures_across_codes import multi_code
    games = _league(client, arsenal, 4)
    upload(client, json.dumps(multi_code("YYY", [(g, "18", "total=1.5", "Over 1.5") for g in games])))
    html = client.get("/code/YYY?todds=4&minp=65").get_data(as_text=True)
    section = html.split("Same odds, higher chance")[1].split("Played this code?")[0]
    chances = [float(x) for x in re.findall(r'data-label="Chance" class="num">([\d.]+)%', section)]
    assert chances and min(chances) >= 65


def brute_k(games, goal, k):
    best = None
    for choice in itertools.product(*[[None] + g for g in games]):
        legs = [c for c in choice if c]
        if len(legs) != k or math.prod(c["odds"] for c in legs) < goal:
            continue
        p = math.prod(c["prob"] for c in legs)
        best = p if best is None or p > best else best
    return best


def test_best_by_legs_matches_brute_force():
    rng = random.Random(11)
    for np_on in (True, False):
        saved = target.np
        if not np_on:
            target.np = None
        try:
            for _ in range(40):
                games = [game(rng, rng.randint(1, 3)) for _ in range(rng.randint(1, 5))]
                goal = rng.uniform(1.3, 6)
                K = rng.randint(1, 4)
                got = dict(target.best_by_legs(games, goal, K))
                for k in range(1, K + 1):
                    want = brute_k(games, goal * 1.005, k)
                    if k in got:
                        t = target.totals(got[k])
                        assert t["n"] == k and t["odds"] >= goal * 0.995
                        ids = [next(i for i, g in enumerate(games) if l in g) for l in got[k]]
                        assert len(set(ids)) == k
                        if want is not None:
                            assert t["prob"] >= want - 1e-12
                    else:
                        assert want is None
        finally:
            target.np = saved


def test_max_legs_limits_and_agrees_with_unlimited():
    rng = random.Random(5)
    games = [game(rng, 3) for _ in range(8)]
    best = target.totals(target.best_for_odds(games, 4))
    by = target.best_by_legs(games, 4, 8)
    top = max((target.totals(l) for _, l in by), key=lambda t: t["prob"])
    assert abs(top["prob"] - best["prob"]) < 1e-9
    assert all(k <= 2 for k, _ in target.best_by_legs(games, 4, 2))
