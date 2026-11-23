"""Audit of the maths against SportyBet's own prices.

Runs on the Arsenal v Leeds response and on every game found in tests/fixtures/real/ (add real exports there).
Each check uses only SportyBet's numbers, independently of how the app prices a pick:
  - full-time goal picks: SportyBet's probability must lie between the correct-score probabilities summed over the
    scores where the app says the pick wins, with SportyBet's "other" scores counted as all losing or all winning;
  - the same with the half-time/full-time correct score, for picks that depend on the halves;
  - refund picks: SportyBet's figure is the chance of winning given no refund;
  - double chance: probabilities add up to 2 and match 1X2; the whole-market margin uses k = 2.
"""
import glob
import json
import math
import os

import pytest

from app.analysis import bettypes, codes, markets, picks, settle
from app.sources.sportybet.importer import extract_all_json, is_har, _har_bodies
from app.sources.sportybet.parse import classify

HERE = os.path.dirname(__file__)


def _games():
    out = [("arsenal_leeds", json.loads(open(os.path.join(HERE, "fixtures", "arsenal_leeds.json"), encoding="utf-8")
                                        .read(), strict=False)["data"])]
    for path in sorted(glob.glob(os.path.join(HERE, "fixtures", "real", "*.json")) +
                       glob.glob(os.path.join(HERE, "fixtures", "real", "*.har"))):
        objs = extract_all_json(open(path, encoding="utf-8", errors="replace").read())
        bodies = []
        for o in objs:
            bodies += [x for b in _har_bodies(o) for x in extract_all_json(b)] if is_har(o) else [o]
        for o in bodies:
            kind = classify(o)
            evs = [o["data"]] if kind == "event" else (
                [e for lg in o["data"] for e in lg.get("events", [])] if kind == "league" else [])
            for e in evs:
                if e.get("markets"):
                    out.append((f'{os.path.basename(path)}:{e.get("eventId")}', e))
    return out


GAMES = _games()
IDS = [g[0] for g in GAMES]


def _ft_states(win, push):
    grid = markets._GRIDS["goals"]
    ft = {}
    for i, (h1, a1, h2, a2) in enumerate(grid):
        st = "w" if win >> i & 1 else ("p" if push >> i & 1 else "l")
        if ft.setdefault((h1 + h2, a1 + a2), st) != st:
            return None                                  # depends on the halves
    return ft


def _bounds_ok(sb, pw, pp, other, push, tol=0.006):
    if push:
        if pp >= 1:
            return True
        lo, hi = pw / (1 - pp), (pw + other) / (1 - pp)
    else:
        lo, hi = pw, pw + other
    return lo - tol <= sb <= hi + tol


@pytest.mark.parametrize("ev", [g[1] for g in GAMES], ids=IDS)
def test_full_time_picks_agree_with_correct_score(ev):
    cs = next((m for m in ev["markets"] if m.get("id") == "45" and not m.get("specifier")), None)
    if not cs or any(o.get("isActive") != 1 for o in cs["outcomes"]):
        pytest.skip("no complete correct-score market in this game")
    P, other = {}, 0.0
    for o in cs["outcomes"]:
        p = float(o["probability"])
        if ":" in o["desc"]:
            h, a = map(int, o["desc"].split(":"))
            P[(h, a)] = p
        else:
            other += p
    bad, n = [], 0
    for k, v in markets.build_priced(ev, "goals").items():
        ft = _ft_states(v["win"], v["push"])
        if ft is None:
            continue
        pw = sum(P.get(s, 0) for s, st in ft.items() if st == "w")
        pp = sum(P.get(s, 0) for s, st in ft.items() if st == "p")
        sb = v.get("prob_cond", v["prob"]) if v["push"] else v["prob"]
        n += 1
        if not _bounds_ok(sb, pw, pp, other, v["push"]):
            bad.append((k, sb, pw, pw + other))
    assert n > 0 and not bad, bad[:10]


@pytest.mark.parametrize("ev", [g[1] for g in GAMES], ids=IDS)
def test_half_dependent_picks_agree_with_ht_ft_correct_score(ev):
    m = next((m for m in ev["markets"] if m.get("id") == "46"), None)
    if not m or any(o.get("isActive") != 1 for o in m["outcomes"]):
        pytest.skip("no complete half-time/full-time correct-score market in this game")
    idx = {c: i for i, c in enumerate(markets._GRIDS["goals"])}
    J, other = {}, 0.0
    for o in m["outcomes"]:
        parts = o["desc"].split()
        p = float(o["probability"])
        if len(parts) == 2 and all(":" in x for x in parts):
            (h1, a1), (h, a) = (map(int, x.split(":")) for x in parts)
            J[(h1, a1, h - h1, a - a1)] = p
        else:
            other += p
    bad = []
    for k, v in markets.build_priced(ev, "goals").items():
        pw = sum(p for c, p in J.items() if c in idx and v["win"] >> idx[c] & 1)
        pp = sum(p for c, p in J.items() if c in idx and v["push"] >> idx[c] & 1)
        sb = v.get("prob_cond", v["prob"]) if v["push"] else v["prob"]
        if not _bounds_ok(sb, pw, pp, other, v["push"]):
            bad.append((k, sb, pw, pw + other))
    assert not bad, bad[:10]


@pytest.mark.parametrize("ev", [g[1] for g in GAMES], ids=IDS)
def test_refund_picks_are_chances_given_no_refund(ev):
    pr = markets.build_priced(ev, "goals")
    h, d, a = (pr.get(f"1X2: {x}") for x in ("Home", "Draw", "Away"))
    dnb = pr.get("Draw No Bet: Home")
    if h and d and a and dnb:
        assert abs(dnb["prob_cond"] - h["prob"] / (h["prob"] + a["prob"])) < 0.003
        assert abs(dnb["prob"] - h["prob"]) < 0.003                     # outright: wins exactly when 1X2 Home wins
        assert abs(dnb["push_prob"] - d["prob"]) < 0.003                # refund: exactly on a draw
    for line in (1, 2, 3):
        over = pr.get(f"Total: Over {line}")
        lo, hi = pr.get(f"Total: Over {line - 0.5}"), pr.get(f"Total: Over {line + 0.5}")
        if over and lo and hi and not over.get("cond"):
            assert abs(over["prob"] - hi["prob"]) < 0.003               # outright: more than the line
            assert abs(over["push_prob"] - (lo["prob"] - hi["prob"])) < 0.003


@pytest.mark.parametrize("ev", [g[1] for g in GAMES], ids=IDS)
def test_double_chance_and_margins(ev):
    M = {(m["id"], m.get("specifier") or ""): m for m in ev["markets"]}
    dc, x12 = M.get(("10", "")), M.get(("1", ""))
    if not dc or not x12:
        pytest.skip("no double chance or 1X2")
    p = {o["desc"]: float(o["probability"]) for o in x12["outcomes"]}
    q = {o["desc"]: float(o["probability"]) for o in dc["outcomes"]}
    assert abs(sum(q.values()) - 2) < 0.01
    for name, (x, y) in {"Home or Draw": ("Home", "Draw"), "Draw or Away": ("Draw", "Away"),
                         "Home or Away": ("Home", "Away")}.items():
        assert abs(q[name] - (p[x] + p[y])) < 0.005
    chk = bettypes.market_checks(ev)
    ok, kept = chk[("10", "")]
    if all(o.get("isActive") == 1 for o in dc["outcomes"]):
        assert ok and abs(kept - (1 - 2 / sum(1 / float(o["odds"]) for o in dc["outcomes"]))) < 1e-12
    ok, kept = chk[("1", "")]
    if ok and kept is not None:
        assert 0 <= kept < 0.15


@pytest.mark.parametrize("ev", [g[1] for g in GAMES], ids=IDS)
def test_no_reliable_pick_pays_more_than_it_costs(ev):
    chk = bettypes.market_checks(ev)
    for f in markets.FAMILIES:
        for k, v in markets.build_priced(ev, f).items():
            if chk.get((v["mid"], v["spec"]), (False, None))[0] and not v.get("cond"):
                assert v["ret"] <= 1.0 + 1e-9, (k, v["odds"], v["prob"])


def test_running_return_counts_refunds(arsenal):
    pr = markets.build_priced(arsenal, "goals")
    rows = [dict(pr["Draw No Bet: Home"]), dict(pr["Total: Over 2"]), dict(pr["1X2: Home"])]
    picks.with_running_accumulator(rows)
    assert abs(rows[-1]["acc_ret"] - math.prod(r["ret"] for r in rows)) < 1e-12
    assert rows[-1]["acc_ret"] > rows[-1]["acc_odds"] * rows[-1]["acc_prob"]       # refunds add to the return


def test_same_game_estimate_counts_refunds(arsenal):
    pr = markets.build_priced(arsenal, "goals")
    a, b = pr["Draw No Bet: Home"], pr["Total: Over 2"]
    legs = [{"event_id": "x", "odds": v["odds"], "prob": v["prob"], "ret": v["ret"], "market_id": None} for v in (a, b)]
    unit = codes.combine_same_game(legs)[0]
    assert unit["how"] == "estimate" and abs(unit["ret"] - a["ret"] * b["ret"]) < 1e-12


def test_void_leg_counts_as_odds_one():
    legs = [{"event_id": "1", "sel_key": "a", "odds": 2.0, "market_id": "1", "specifier": "", "pick": "Home",
             "match": "A v B"},
            {"event_id": "2", "sel_key": "b", "odds": 1.9, "market_id": "18", "specifier": "total=2",
             "pick": "Over 2", "match": "C v D"}]
    res = {"1": (1, 0, 0, 0), "2": (1, 0, 1, 0)}                 # game 2 ends with exactly 2 goals: refund
    s = settle.settle_code(legs, res, {}, "X")
    assert [l["status"] for l in s["legs"]] == ["won", "void"] and s["status"] == "won" and s["multiplier"] == 2.0
    res["2"] = (0, 0, 1, 0)
    assert settle.settle_code(legs, res, {}, "X")["status"] == "lost"


def test_calibration_counts_each_pick_once():
    leg = {"sel_key": "e|1||1", "status": "won", "prob": 0.7}
    other = {"sel_key": "f|1||1", "status": "lost", "prob": 0.72}
    out = settle.calibration([leg] * 27 + [other])
    assert sum(g["n"] for g in out) == 2
