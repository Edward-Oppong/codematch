"""Picking within a game, and what happens when picks are combined into one code."""
import math

from . import markets

# Risk zones by odds. Lower odds = higher chance in the bookmaker's view, and a lower payout.
# Typical picks: lower risk = double chance, big favourite to win, over 1.5, under 3.5;
# medium = win in an even game, BTTS, over / under 2.5; higher risk = draw, correct score, over 3.5, underdog.
ZONES = [  # (key, label, min odds inclusive, max odds exclusive)
    ("vlow", "Very short", 1.0, 1.10),          # near-certain in the bookmaker's view, pays almost nothing
    ("low", "Lower risk", 1.10, 1.50),
    ("medium", "Medium", 1.50, 2.00),
    ("high", "Higher risk", 2.00, 1000.0),
]
ZONE_LABEL = {k: label for k, label, _, _ in ZONES}


def zone(odds):
    for key, _, lo, hi in ZONES:
        if lo <= odds < hi:
            return key
    return "high"


def zone_range(key):
    for k, _, lo, hi in ZONES:
        if k == key:
            return lo, hi
    return None


def headline(event, priced=None):
    """Main prices for a game list: 1X2, over/under 2.5, both teams to score. priced: the game's picks, if loaded."""
    p = priced if priced is not None else markets.build_priced(event, "goals")
    g = lambda k: p.get(k, {}).get("odds")
    return {"h": g("1X2: Home"), "d": g("1X2: Draw"), "a": g("1X2: Away"),
            "o25": g("Total: Over 2.5"), "u25": g("Total: Under 2.5"), "btts": g("BTTS: Yes")}


def best_pick(event, families, minp=0.0, maxp=1.0, mino=1.0, maxo=1000.0, by="prob", priced=None):
    """The single pick in this game inside the probability and odds window.
    by='prob' takes the most likely; by='return' the one with the smallest bookmaker margin.
    priced: the game's markets already priced with markets.priced_all, to save doing it twice."""
    priced = priced if priced is not None else markets.priced_all(event, families)
    cands = [(k, v) for k, v in priced.items()
             if not v.get("cond") and minp <= v["prob"] <= maxp and mino <= v["odds"] < maxo]
    if not cands:
        return None
    score = (lambda kv: kv[1]["prob"]) if by == "prob" else (lambda kv: kv[1]["ret"])
    k, v = max(cands, key=score)
    return {"pick": k, "odds": v["odds"], "prob": v["prob"], "ret": v["ret"], "family": v["family"],
            "refund_on": v.get("refund_on"), "mid": v["mid"], "spec": v["spec"], "oid": v["oid"],
            "zone": zone(v["odds"])}


def with_running_accumulator(rows):
    """Add, to each row, what a code of this row and every row above it would look like: total odds, the chance
    every leg wins outright, and the average return (refunds included). Different games are treated as independent."""
    odds = prob = ret = 1.0
    for r in rows:
        odds *= r["odds"]
        prob *= r["prob"]
        # a refund pick returns its stake in the refund case, so its return isn't odds x chance of winning outright
        ret *= r["ret"] if r.get("ret") is not None else r["odds"] * r["prob"]
        r["acc_odds"], r["acc_prob"], r["acc_ret"] = odds, prob, ret
    return rows


def accumulator(legs):
    """Total odds, chance and expected return of a set of legs (dicts with odds and prob)."""
    if not legs:
        return None
    odds = math.prod(l["odds"] for l in legs)
    probs = [l.get("prob") for l in legs]
    if any(p is None for p in probs):
        return {"odds": odds, "prob": None, "ret": None}
    prob = math.prod(probs)
    return {"odds": odds, "prob": prob, "ret": odds * prob}
