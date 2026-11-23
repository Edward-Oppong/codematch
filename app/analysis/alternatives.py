"""Safer and riskier picks on the same game, from the result masks in markets.py."""
from .markets import covers


def alternatives(priced, label=None, base=None):
    """Safer picks (do at least as well in every result) and riskier ones (do no better anywhere, win somewhere),
    one per distinct outcome pattern: the best-priced safer pick and the shortest-priced riskier pick.
    base: a pick that isn't in priced itself (an early-payout pick), given by its masks."""
    base = base if base is not None else priced[label]
    key = lambda v: (v["win"], v["push"], v.get("maybe", 0))
    safer, riskier = {}, {}
    for k, v in priced.items():
        if k == label or key(v) == key(base):
            continue
        if covers(v, base):
            cur = safer.get(key(v))
            if cur is None or v["odds"] > cur[1]["odds"]:
                safer[key(v)] = (k, v)
        elif covers(base, v) and v["win"]:
            cur = riskier.get(key(v))
            if cur is None or v["odds"] < cur[1]["odds"]:
                riskier[key(v)] = (k, v)
    s = sorted(safer.values(), key=lambda kv: kv[1]["prob"])           # closest first
    r = sorted(riskier.values(), key=lambda kv: -kv[1]["prob"])
    return s, r


def consistency_check(priced, tol=0.01):
    """If A wins only on results where B also wins, B should be at least as likely to win. Return violations."""
    bad = []
    items = [(k, v) for k, v in priced.items() if not v.get("cond")]
    for ka, a in items:
        for kb, b in items:
            if a["win"] != b["win"] and (a["win"] & ~b["win"]) == 0 and b["prob"] + tol < a["prob"]:
                bad.append((ka, kb, a["prob"], b["prob"]))
    return bad
