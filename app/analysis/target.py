"""Reach a total odds with the highest chance of winning.

For any pick, odds x chance = return, and SportyBet keeps every return below 1. For a code of legs on different
games the returns multiply, so

    chance of the code = (product of the legs' returns) / total odds

At a fixed total odds the chance depends only on how much margin the legs carry together. The best code for given
odds is therefore the one that loses least to the margin: usually fewer legs, and legs with small margins. Stacking
very short picks is the most expensive way to build odds, because each one adds almost as much margin as odds.

best_for_odds() searches for that code (exactly, apart from rounding each leg's odds to a fine grid, so a
code can land a hair under the target, well inside the rounding SportyBet shows): at most one pick per game, total
odds at or above the target, highest chance. stack_safest() builds the same odds the usual way, adding each game's
most likely pick until the odds are reached, so the two can be compared.
"""
import math

try:                    # optional: makes the search about 20 times faster on a full league weekend
    import numpy as np
except ImportError:     # pragma: no cover
    np = None

TOL = 0.995          # "reached" allows the same half percent in stack_safest, so the two are compared fairly
STEPS = 1000         # resolution of the odds in the search: the result lands within about half a percent of the target


def frontier(cands):
    """The picks in one game that no other pick beats on both odds and chance. Only these can be in the best code."""
    out, best = [], 0.0
    for c in sorted(cands, key=lambda c: (-c["prob"], -c["odds"])):
        if c["odds"] > best + 1e-12:
            out.append(c)
            best = c["odds"]
    return out


def usable(c):
    return c.get("prob") is not None and 0 < c["prob"] <= 1 and c.get("odds") and c["odds"] > 1


def best_for_odds(games, target):
    """games: one list of candidate picks per game (dicts with at least 'odds' and 'prob').
    Returns the list of chosen picks (at most one per game) with total odds >= target and the highest chance,
    or None when the target can't be reached with these picks."""
    if not target or target <= 1:
        return None
    games = [frontier([c for c in g if usable(c)]) for g in games]
    games = [g for g in games if g]
    W = STEPS
    step = math.log(target) / W
    NEG = -math.inf
    dp = [NEG] * (W + 1)               # dp[w] = best sum of log(chance) with odds worth w steps (w = W: target reached)
    dp[0] = 0.0
    trail = []                          # per game: {w: (pick index, previous w)} for the cells this game improved
    for g in games:
        items = []
        for i, c in enumerate(g):
            w = int(math.log(c["odds"]) / step + 0.5)  # nearest step: 1.25 x 1.60 must still count as reaching 2.00
            if w > 0:
                items.append((i, min(w, W), math.log(c["prob"])))
        # picks that reach the target on their own all land in the last cell: only the most likely matters
        whole = [it for it in items if it[1] >= W]
        items = [it for it in items if it[1] < W] + ([max(whole, key=lambda it: it[2])] if whole else [])
        if np is not None:
            dp, moves = _step_np(dp, items, W)
        else:
            dp, moves = _step_py(dp, items, W)
        trail.append(moves)
    if dp[W] == NEG:
        return None
    chosen, w = [], W
    for g, moves in zip(reversed(games), reversed(trail)):
        if w in moves:
            i, prev = moves[w]
            # this game's move set dp[w] only if no later game overwrote it; walking backwards keeps that consistent
            chosen.append(g[i])
            w = prev
        if w == 0:
            break
    chosen.reverse()
    return chosen


def _step_py(dp, items, W):
    NEG = -math.inf
    new, moves = dp[:], {}
    reach = [s for s in range(W + 1) if dp[s] != NEG]
    for i, w, lp in items:
        for s in reach:
            t = s + w if s + w < W else W
            v = dp[s] + lp
            if v > new[t] + 1e-15:
                new[t] = v
                moves[t] = (i, s)
    return new, moves


def _step_np(dp, items, W):
    cur = np.asarray(dp, dtype=float)
    new = cur.copy()
    pick = np.full(W + 1, -1)
    prev = np.zeros(W + 1, dtype=int)
    idx = np.arange(W + 1)
    for i, w, lp in items:
        cand = np.full(W + 1, -np.inf)
        src = np.full(W + 1, -1)
        cand[w:W] = cur[:W - w] + lp                     # from s to s + w, below the target
        src[w:W] = idx[:W - w]
        tail = cur[max(0, W - w):] + lp                  # every s that reaches the target lands on W
        if tail.size:
            j = int(np.argmax(tail))
            cand[W], src[W] = tail[j], max(0, W - w) + j
        better = cand > new + 1e-15
        new[better] = cand[better]
        pick[better] = i
        prev[better] = src[better]
    moves = {int(t): (int(pick[t]), int(prev[t])) for t in np.nonzero(pick >= 0)[0]}
    return new.tolist(), moves


def best_by_legs(games, target, max_legs):
    """Like best_for_odds, with at most max_legs picks, and the best code for every number of picks.
    Returns [(number of picks, picks)] for each number of picks from 1 to max_legs that can reach the target,
    each the highest-chance way to do it with exactly that many picks (one pick per game at most)."""
    if not target or target <= 1 or not max_legs or max_legs < 1:
        return []
    games = [frontier([c for c in g if usable(c)]) for g in games]
    games = [g for g in games if g]
    K, W = min(int(max_legs), len(games)), STEPS
    if K < 1:
        return []
    step = math.log(target) / W
    NEG = -math.inf
    dp = [[NEG] * (W + 1) for _ in range(K + 1)]     # dp[k][w]: best sum of log(chance) with k picks, odds worth w steps
    dp[0][0] = 0.0
    trail = []
    for g in games:
        items = []
        for i, c in enumerate(g):
            w = int(math.log(c["odds"]) / step + 0.5)
            if w > 0:
                items.append((i, min(w, W), math.log(c["prob"])))
        whole = [it for it in items if it[1] >= W]
        items = [it for it in items if it[1] < W] + ([max(whole, key=lambda it: it[2])] if whole else [])
        dp, moves = (_step2_np if np is not None else _step2_py)(dp, items, W, K)
        trail.append(moves)
    out = []
    for k in range(1, K + 1):
        if dp[k][W] == NEG:
            continue
        chosen, kk, w = [], k, W
        for g, moves in zip(reversed(games), reversed(trail)):
            if (kk, w) in moves:
                i, prev = moves[(kk, w)]
                chosen.append(g[i])
                kk, w = kk - 1, prev
            if kk == 0:
                break
        chosen.reverse()
        out.append((k, chosen))
    return out


def _step2_py(dp, items, W, K):
    NEG = -math.inf
    new = [row[:] for row in dp]
    moves = {}
    reach = [(k, s) for k in range(K) for s in range(W + 1) if dp[k][s] != NEG]
    for i, w, lp in items:
        for k, s in reach:
            t = s + w if s + w < W else W
            v = dp[k][s] + lp
            if v > new[k + 1][t] + 1e-15:
                new[k + 1][t] = v
                moves[(k + 1, t)] = (i, s)
    return new, moves


def _step2_np(dp, items, W, K):
    cur = np.asarray(dp, dtype=float)                  # shape (K + 1, W + 1)
    new = cur.copy()
    pick = np.full(cur.shape, -1)
    prev = np.zeros(cur.shape, dtype=int)
    idx = np.broadcast_to(np.arange(W + 1), cur.shape)
    for i, w, lp in items:
        cand = np.full(cur.shape, -np.inf)
        src = np.full(cur.shape, -1)
        cand[1:, w:W] = cur[:-1, :W - w] + lp           # one more pick, from s to s + w
        src[1:, w:W] = idx[:-1, :W - w]
        lo = max(0, W - w)
        tail = cur[:-1, lo:] + lp                       # reaching the target lands on W
        j = np.argmax(tail, axis=1)
        cand[1:, W] = tail[np.arange(K), j]
        src[1:, W] = lo + j
        better = cand > new + 1e-15
        new[better] = cand[better]
        pick[better] = i
        prev[better] = src[better]
    ks, ts = np.nonzero(pick >= 0)
    moves = {(int(k), int(t)): (int(pick[k, t]), int(prev[k, t])) for k, t in zip(ks, ts)}
    return new.tolist(), moves


def best_with_min_legs(games, target, min_legs, cap=15):
    """The highest-chance code reaching the target odds with at least min_legs picks (one per game), or None.
    Codes much longer than needed lose chance with every extra leg, so lengths are searched up to
    max(min_legs, cap)."""
    if not min_legs or min_legs <= 1:
        return best_for_odds(games, target)
    found = [legs for k, legs in best_by_legs(games, target, max(int(min_legs), cap)) if k >= min_legs]
    return max(found, key=lambda legs: math.prod(l["prob"] for l in legs), default=None)


def stack_safest(games, target):
    """The usual way: each game's most likely pick, most likely first, added until the total odds reach the target.
    Returns the picks, or None if even all of them don't reach it."""
    tops = [max((c for c in g if usable(c)), key=lambda c: (c["prob"], c["odds"]), default=None) for g in games]
    tops = sorted((t for t in tops if t), key=lambda c: -c["prob"])
    out, odds = [], 1.0
    for t in tops:
        if odds >= target * TOL:
            break
        out.append(t)
        odds *= t["odds"]
    return out if odds >= target * TOL else None


def totals(legs):
    """Total odds, chance and return of picks on different games."""
    if not legs:
        return None
    odds = math.prod(l["odds"] for l in legs)
    prob = math.prod(l["prob"] for l in legs)
    return {"odds": odds, "prob": prob, "ret": odds * prob, "n": len(legs)}


def from_priced(event_id, match, priced, minp=0.0, maxp=1.0, mino=1.0, maxo=1000.0):
    """Candidate picks from one game's priced markets ({label: pick} from markets.build_priced / priced_all).
    Refund picks are left out: their 'chance' isn't the chance of being paid in full, so they can't be combined
    on the same footing."""
    from .picks import zone
    out = []
    for k, v in priced.items():
        if v.get("cond") or v.get("push") or v.get("prob") is None:
            continue
        if not (minp <= v["prob"] <= maxp and mino <= v["odds"] < maxo):
            continue
        out.append({"event_id": event_id, "match": match, "label": k, "odds": v["odds"], "prob": v["prob"],
                    "ret": v["ret"], "family": v.get("family"), "zone": zone(v["odds"]),
                    "sel": {"eventId": event_id, "marketId": v["mid"], "specifier": v["spec"], "outcomeId": v["oid"]}})
    return out
