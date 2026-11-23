"""Settle booking-code legs against final scores, and keep score of money staked and returned.

Goal markets settle automatically from the half-time and full-time score, using the same rules that decide
which results each pick wins on. Bookings, corners and markets the app doesn't model need a manual result.
"""
import datetime
import math
from collections import defaultdict

from . import markets

AFTER_KICKOFF_MS = 2.5 * 3600 * 1000      # a game is assumed finished this long after kick-off


def leg_status(leg, result, manual=None):
    """'won', 'lost', 'void', or 'pending' (no score yet) or 'manual' (needs a manual result)."""
    if manual:
        return manual
    names = tuple((leg.get("match") or " v ").split(" v ", 1))
    early = markets.early_info(leg.get("market_id"), leg["pick"], names)
    if early:
        # surely won when the team won; surely lost when it never scored enough to lead by the margin;
        # otherwise only the match's course says, so it's marked by hand
        if result is None:
            return "pending"
        h, a = result[0] + result[2], result[1] + result[3]
        if markets.RES[early["side"]](h, a):
            return "won"
        if early["side"] == "Draw" or (h if early["side"] == "Home" else a) < early["early"]:
            return "lost"
        return "manual"
    c = markets.classify_outcome(leg.get("market_id"), leg.get("specifier") or "", leg["pick"], names)
    if not c or c[0] != "goals":
        return "manual"
    if result is None:
        return "pending"
    _, _, win, push = c
    if win(result):
        return "won"
    if push is not None and push(result):
        return "void"
    return "lost"


def code_status(statuses):
    """A code loses as soon as one leg loses; it wins when every leg has won or been voided."""
    if "lost" in statuses:
        return "lost"
    if any(s in ("pending", "manual") for s in statuses):
        return "pending"
    return "won"


def settle_code(legs, results, manual, code):
    rows = []
    for l in legs:
        s = leg_status(l, results.get(l["event_id"]), manual.get((code, l["sel_key"])))
        rows.append({**l, "status": s})
    status = code_status([r["status"] for r in rows])
    mult = math.prod(r["odds"] for r in rows if r["status"] == "won") if status == "won" else 0.0
    return {"legs": rows, "status": status, "multiplier": mult}


def bucket(n_legs):
    for hi, name in ((1, "single"), (3, "2-3 legs"), (9, "4-9 legs"), (19, "10-19 legs")):
        if n_legs <= hi:
            return name
    return "20+ legs"


def money(bets_, settled_by_code, legs_by_code, now_ms):
    """Totals overall, per month and per code size. A bet's payout is what was recorded, or worked out from
    its legs once every leg is settled; bets still running count as pending."""
    month = datetime.datetime.fromtimestamp(now_ms / 1000, datetime.timezone.utc).strftime("%Y-%m")
    tot = {"staked": 0.0, "returned": 0.0, "pending": 0.0, "n": 0, "won": 0, "lost": 0}
    by_month = defaultdict(lambda: {"staked": 0.0, "returned": 0.0, "pending": 0.0, "n": 0, "won": 0})
    by_size = defaultdict(lambda: {"staked": 0.0, "returned": 0.0, "n": 0, "won": 0})
    rows = []
    for b in bets_:
        s = settled_by_code.get(b["code"])
        n_legs = len(legs_by_code.get(b["code"], [])) or None
        if b["payout"] is not None:
            payout, status = b["payout"], ("won" if b["payout"] > 0 else "lost")
        elif s and s["status"] != "pending":
            payout, status = b["stake"] * s["multiplier"], s["status"]
        else:
            payout, status = None, "pending"
        m = datetime.datetime.fromtimestamp(b["placed_at"], datetime.timezone.utc).strftime("%Y-%m")
        rows.append({**b, "status": status, "payout_calc": payout, "n_legs": n_legs, "month": m})
        for agg in (tot, by_month[m]):
            agg["staked"] += b["stake"]
            agg["n"] += 1
            if payout is None:
                agg["pending"] += b["stake"]
            else:
                agg["returned"] += payout
                agg["won"] += payout > 0
        if payout is not None:
            tot["lost"] += payout == 0
            if n_legs:
                z = by_size[bucket(n_legs)]
                z["staked"] += b["stake"]
                z["returned"] += payout
                z["n"] += 1
                z["won"] += payout > 0
    settled = tot["staked"] - tot["pending"]
    tot["net"] = tot["returned"] - settled
    for v in by_month.values():
        v["net"] = v["returned"] - (v["staked"] - v["pending"])
    order = ["single", "2-3 legs", "4-9 legs", "10-19 legs", "20+ legs"]
    return {"total": tot, "this_month": by_month.get(month, {"staked": 0.0, "returned": 0.0, "pending": 0.0,
                                                               "n": 0, "won": 0, "net": 0.0}),
            "month": month, "months": sorted(by_month.items(), reverse=True),
            "sizes": [(k, by_size[k]) for k in order if k in by_size], "rows": rows}


def calibration(settled_legs):
    """Did SportyBet's chances come true? Settled legs grouped by stated chance: how many, the average stated
    chance, and how often they actually won. Voided legs are left out, and each pick counts once however many codes
    hold it. For a refund pick SportyBet's figure is the chance of winning when there's no refund, which is exactly
    what its won / lost record measures."""
    edges = [0, 0.3, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 1.01]
    groups = defaultdict(list)
    seen = set()
    for l in settled_legs:
        # the same pick in several codes is one result, not several
        key = l.get("sel_key") or (l.get("event_id"), l.get("market_id"), l.get("specifier"), l.get("outcome_id"))
        if key in seen:
            continue
        seen.add(key)
        if l["status"] in ("won", "lost") and l.get("prob") is not None:
            for lo, hi in zip(edges, edges[1:]):
                if lo <= l["prob"] < hi:
                    groups[(lo, hi)].append(l)
                    break
    out = []
    for (lo, hi), ls in sorted(groups.items()):
        n = len(ls)
        won = sum(1 for l in ls if l["status"] == "won")
        stated = sum(l["prob"] for l in ls) / n
        # rough 95% range for the real win rate with this many legs
        se = math.sqrt(max(stated * (1 - stated), 1e-9) / n)
        out.append({"range": f"{lo * 100:.0f}-{min(hi, 1) * 100:.0f}%", "n": n, "stated": stated,
                    "actual": won / n, "low": max(0.0, stated - 2 * se), "high": min(1.0, stated + 2 * se)})
    return out


POPULAR = 5        # a Code Hub code used by at least this many people counts as popular in the track record


def hub_record(codes_):
    """How Code Hub codes did, against SportyBet's own chances. codes_ = [{'popularity', 'status', 'multiplier',
    'prob', 'ret'}] (status 'won' or 'lost' counts; others are skipped); prob is the code's chance and ret its average
    return per 1, both from SportyBet's numbers when the code was fetched.
    For each group: codes, wins, the wins SportyBet's chances expect and a range around it (about 95%), and what
    1 staked on every code would have returned against what was expected."""
    groups = {"all": [], "popular": [], "rest": []}
    for c in codes_:
        if c["status"] not in ("won", "lost") or c.get("prob") is None:
            continue
        groups["all"].append(c)
        groups["popular" if (c.get("popularity") or 0) >= POPULAR else "rest"].append(c)
    out = []
    names = {"all": "Every Code Hub code", "popular": f"Used by {POPULAR} or more",
             "rest": f"Used by fewer than {POPULAR}"}
    for key, cs in groups.items():
        if not cs:
            continue
        mean = sum(c["prob"] for c in cs)
        sd = math.sqrt(sum(c["prob"] * (1 - c["prob"]) for c in cs))
        won = sum(1 for c in cs if c["status"] == "won")
        out.append({"key": key, "name": names[key], "n": len(cs), "won": won, "expected": mean,
                    "low": max(0.0, mean - 2 * sd), "high": mean + 2 * sd,
                    "returned": sum(c["multiplier"] for c in cs if c["status"] == "won"),
                    "ret_expected": sum(c["ret"] for c in cs if c.get("ret") is not None)})
    return out


def clv_analysis(bets_, legs_by_code, con):
    """Analyze Closing Line Value (CLV) across recorded bets: compare placed odds against closing odds.
    Beating the closing line consistently (+CLV) is the statistical proof of positive expected value."""
    if not bets_:
        return {"n": 0, "beat": 0, "beat_pct": 0.0, "avg_clv": 0.0, "expected_pnl": 0.0, "realized_pnl": 0.0, "items": []}

    items = []
    tot_stake = 0.0
    tot_weighted_clv = 0.0
    tot_exp_pnl = 0.0
    tot_real_pnl = 0.0
    beat_count = 0

    for b in bets_:
        code = b["code"]
        legs = legs_by_code.get(code, [])
        if not legs:
            continue
        placed_odds = math.prod(l["odds"] for l in legs) if legs else 0.0
        if placed_odds <= 1.0:
            continue

        close_odds_list = []
        for l in legs:
            eid = l["event_id"]
            lbl = f'{l["market"]}: {l["pick"]}'
            r = con.execute("""
                SELECT odds FROM history WHERE event_id=? AND label=? ORDER BY ts DESC LIMIT 1
            """, (eid, lbl)).fetchone()
            if not r:
                r = con.execute("""
                    SELECT odds FROM picks WHERE event_id=? AND label=?
                """, (eid, lbl)).fetchone()
            close_odds = r[0] if r else l["odds"]
            close_odds_list.append(close_odds)

        closing_odds = math.prod(close_odds_list)
        if closing_odds <= 0:
            continue

        clv_ratio = (placed_odds / closing_odds) - 1.0
        clv_pct = clv_ratio * 100.0
        beat = placed_odds > closing_odds + 1e-4
        if beat:
            beat_count += 1

        stake = b["stake"]
        tot_stake += stake
        tot_weighted_clv += stake * clv_pct
        exp_pnl = stake * clv_ratio
        tot_exp_pnl += exp_pnl
        pnl = (b["payout"] - stake) if b.get("payout") is not None else 0.0
        tot_real_pnl += pnl

        items.append({
            "code": code,
            "placed_odds": placed_odds,
            "closing_odds": closing_odds,
            "clv_pct": clv_pct,
            "beat": beat,
            "stake": stake,
            "payout": b.get("payout"),
            "exp_pnl": exp_pnl,
            "real_pnl": pnl
        })

    n = len(items)
    avg_clv = (tot_weighted_clv / tot_stake) if tot_stake > 0 else 0.0
    beat_pct = (beat_count / n * 100.0) if n > 0 else 0.0

    return {
        "n": n,
        "beat": beat_count,
        "beat_pct": beat_pct,
        "avg_clv": avg_clv,
        "expected_pnl": tot_exp_pnl,
        "realized_pnl": tot_real_pnl,
        "items": items
    }
