"""Results: what was staked, what came back, and whether SportyBet's chances came true."""
from collections import Counter
from flask import Blueprint, redirect, render_template, request, url_for

from . import back_to, now_ms
from .. import store
from ..analysis import settle
from ..analysis import calibrate as calib_engine
from ..db import get_db
from ..sources.sportybet import snippets

bp = Blueprint("results", __name__, url_prefix="/results")


def _money(v):
    try:
        x = float(str(v).replace(",", "").strip())
        return x if x >= 0 else None
    except ValueError:
        return None


def record_hub(con, hub=None, legs_by_code=None, settled=None):
    """Keep the outcome of every finished Code Hub code, so the track record outlives the codes."""
    import sqlite3
    from ..analysis import codes as review
    if hub is None:
        hub = {c["code"]: c for c in store.codes(con) if c.get("source") == "hub"}
        res, manual = store.results(con), store.manual_results(con)
        all_legs = store.load_all_legs(con)
        legs_by_code = {c: all_legs.get(c, []) for c in hub}
        settled = {c: settle.settle_code(legs_by_code[c], res, manual, c) for c in hub}
    try:
        existing = {r["code"] for r in con.execute("SELECT code FROM hub_outcomes")}
        dirty = False
        for c in hub:
            st = settled.get(c)
            if not st:
                continue
            if st["status"] in ("won", "lost"):
                if c not in existing:
                    sm = review.summarise(legs_by_code[c])
                    store.save_hub_outcome(con, c, hub[c].get("popularity"), sm["joint_prob"], sm["exp_return"],
                                           st["status"], st["multiplier"], len(legs_by_code[c]))
                    existing.add(c)
                    dirty = True
            elif c in existing:       # only delete if it was previously recorded
                con.execute("DELETE FROM hub_outcomes WHERE code=?", (c,))
                existing.remove(c)
                dirty = True
        if dirty:
            con.commit()
    except sqlite3.OperationalError:
        pass


@bp.get("/")
def index(msgs=()):
    con = get_db()
    res, manual = store.results(con), store.manual_results(con)
    codes = [c["code"] for c in store.codes(con)]
    all_legs_map = store.load_all_legs(con)
    legs_by_code = {c: all_legs_map.get(c, []) for c in codes}
    settled = {c: settle.settle_code(legs, res, manual, c) for c, legs in legs_by_code.items()}
    bets_ = store.bets(con)
    # once a played code is fully settled, keep its payout with the bet, so the record survives deleting the code
    for b in bets_:
        s = settled.get(b["code"])
        if b["payout"] is None and s and s["status"] != "pending":
            b["payout"] = round(b["stake"] * s["multiplier"], 2)
            store.set_payout(con, b["id"], b["payout"])
    now = now_ms()
    m = settle.money(bets_, settled, legs_by_code, now)
    cfg = store.settings(con)
    limit = cfg.get("monthly_limit")
    bankroll = cfg.get("bankroll")
    kelly_fraction = cfg.get("kelly_fraction", 0.25)
    clv = settle.clv_analysis(bets_, legs_by_code, con)

    started = lambda l: (l.get("start_ms") or 0) + settle.AFTER_KICKOFF_MS < now
    all_legs = [l for s in settled.values() for l in s["legs"]]
    edge_rows = calib_engine.market_edge(all_legs)
    edge_summary = calib_engine.overall_edge_summary(edge_rows)
    ktier = calib_engine.kelly_tier(all_legs)
    need_score = {(l["event_id"], l["match"]) for l in all_legs if l["status"] == "pending" and started(l)}

    # Also include any past imported games in `events` that don't have a final score yet
    past_unsettled = con.execute("""
        SELECT e.event_id, e.home, e.away, e.start_ms 
        FROM events e 
        LEFT JOIN results r ON r.event_id = e.event_id 
        WHERE r.event_id IS NULL AND (e.start_ms + ?) < ?
        ORDER BY e.start_ms DESC LIMIT 80
    """, (settle.AFTER_KICKOFF_MS, now)).fetchall()
    for row in past_unsettled:
        need_score.add((row["event_id"], f"{row['home']} v {row['away']}"))

    # Build predictions vs actual results comparison
    settled_comparisons = []
    seen_events = set()
    for l in all_legs:
        if l.get("status") in ("won", "lost", "void"):
            eid = l.get("event_id")
            res_val = res.get(eid)
            score_str = f"{res_val[0] + res_val[2]} - {res_val[1] + res_val[3]} (HT {res_val[0]} - {res_val[1]})" if res_val else None
            prob = l.get("prob")
            settled_comparisons.append({
                "match": l.get("match", ""),
                "market": l.get("market", ""),
                "pick": l.get("pick", ""),
                "odds": l.get("odds", 0),
                "prob": prob,
                "status": l.get("status"),
                "score": score_str,
                "start_ms": l.get("start_ms") or 0,
                "source": "Saved Code"
            })
            if eid:
                seen_events.add(eid)

    # Also extract predictions for finished matches from imported games in results
    finished_events = con.execute("""
        SELECT e.event_id, e.home, e.away, e.start_ms, r.h1, r.a1, r.h2, r.a2
        FROM events e
        JOIN results r ON r.event_id = e.event_id
        ORDER BY e.start_ms DESC LIMIT 30
    """).fetchall()
    for fe in finished_events:
        eid = fe["event_id"]
        if eid in seen_events:
            continue
        res_tuple = (fe["h1"], fe["a1"], fe["h2"], fe["a2"])
        score_str = f"{fe['h1'] + fe['h2']} - {fe['a1'] + fe['a2']} (HT {fe['h1']} - {fe['a1']})"
        match_name = f"{fe['home']} v {fe['away']}"
        top_picks = con.execute("""
            SELECT label, odds, prob, mid, spec, odesc FROM picks
            WHERE event_id = ? AND prob IS NOT NULL AND mid IN ('1', '18', '29', '10')
            ORDER BY prob DESC LIMIT 3
        """, (eid,)).fetchall()
        for p in top_picks:
            leg = {
                "market_id": p["mid"],
                "specifier": p["spec"] or "",
                "pick": p["odesc"] or p["label"].split(": ", 1)[-1],
                "match": match_name
            }
            st = settle.leg_status(leg, res_tuple)
            if st in ("won", "lost", "void"):
                settled_comparisons.append({
                    "match": match_name,
                    "market": p["label"].split(": ")[0] if ": " in p["label"] else "Market",
                    "pick": p["label"].split(": ", 1)[-1],
                    "odds": p["odds"],
                    "prob": p["prob"],
                    "status": st,
                    "score": score_str,
                    "start_ms": fe["start_ms"] or 0,
                    "source": "Imported Game"
                })

    settled_comparisons.sort(key=lambda x: x["start_ms"], reverse=True)
    decided = [c for c in settled_comparisons if c["status"] in ("won", "lost")]
    comp_stats = {
        "total": len(decided),
        "won": sum(1 for c in decided if c["status"] == "won"),
        "win_rate": (sum(1 for c in decided if c["status"] == "won") / len(decided) * 100) if decided else 0,
        "avg_prob": (sum(c["prob"] for c in decided if c["prob"]) / len(decided) * 100) if decided else 0,
    }

    played = {b["code"] for b in bets_}

    # Account Protection Advisor
    tot_net = m["total"]["net"]
    withdrawal_suggested = bool(bankroll and bankroll > 0 and tot_net >= (0.5 * bankroll))
    played_legs = [l for c in played if c in legs_by_code for l in legs_by_code[c]]
    mkt_counts = Counter(calib_engine._market_family(l["market"]) for l in played_legs if l.get("market"))
    tot_played_legs = len(played_legs)
    high_concentration = None
    if tot_played_legs >= 10:
        for fam, count in mkt_counts.items():
            if (count / tot_played_legs) > 0.60:
                high_concentration = (fam, round(count / tot_played_legs * 100))
                break

    account_shield = {
        "withdrawal_suggested": withdrawal_suggested,
        "high_concentration": high_concentration,
        "tot_played_legs": tot_played_legs,
    }

    hub = {c["code"]: c for c in store.codes(con) if c.get("source") == "hub"}
    # Code Hub codes you didn't play don't fill the hand-marking list; the track record counts them as they settle
    need_manual = [(c, l) for c, s in settled.items() for l in s["legs"] if l["status"] == "manual" and started(l)
                   and (c in played or c not in hub)]
    hub_manual = sum(1 for c, s in settled.items() if c in hub and c not in played and s["status"] == "pending"
                     for l in s["legs"] if l["status"] == "manual" and started(l))
    record_hub(con, hub, legs_by_code, settled)
    hub_rec = settle.hub_record(store.hub_outcomes(con))
    need_manual.sort(key=lambda cl: (cl[0] not in played, cl[1].get("start_ms") or 0))
    return render_template(
        "results/index.html", m=m, limit=limit, bankroll=bankroll, kelly_fraction=kelly_fraction, clv=clv,
        codes=codes, msgs=msgs, settled=settled, played=played,
        need_score=len(need_score), score_snippet=snippets.events_snippet(sorted(need_score)[:40]) if need_score else None,
        need_manual=need_manual[:60], n_manual=len(need_manual), calib=settle.calibration(all_legs),
        n_settled=sum(1 for l in all_legs if l["status"] in ("won", "lost")), hub_rec=hub_rec, n_hub=len(hub),
        hub_manual=hub_manual, hub_running=sum(1 for c in hub if settled[c]["status"] == "pending"),
        popular=settle.POPULAR,
        edge_rows=edge_rows, edge_summary=edge_summary, kelly_tier=ktier,
        account_shield=account_shield,
        settled_comparisons=settled_comparisons[:50], comp_stats=comp_stats)


@bp.get("/settlement")
def settlement(msgs=()):
    """Dedicated Match Score Settlement and Predictions vs Actual Reality audit page."""
    con = get_db()
    res, manual = store.results(con), store.manual_results(con)
    codes = [c["code"] for c in store.codes(con)]
    all_legs_map = store.load_all_legs(con)
    legs_by_code = {c: all_legs_map.get(c, []) for c in codes}
    settled = {c: settle.settle_code(legs, res, manual, c) for c, legs in legs_by_code.items()}
    bets_ = store.bets(con)
    played = {b["code"] for b in bets_}
    now = now_ms()

    started = lambda l: (l.get("start_ms") or 0) + settle.AFTER_KICKOFF_MS < now
    all_legs = [l for s in settled.values() for l in s["legs"]]
    need_score = {(l["event_id"], l["match"]) for l in all_legs if l["status"] == "pending" and started(l)}

    past_unsettled = con.execute("""
        SELECT e.event_id, e.home, e.away, e.start_ms 
        FROM events e 
        LEFT JOIN results r ON r.event_id = e.event_id 
        WHERE r.event_id IS NULL AND (e.start_ms + ?) < ?
        ORDER BY e.start_ms DESC LIMIT 80
    """, (settle.AFTER_KICKOFF_MS, now)).fetchall()
    for row in past_unsettled:
        need_score.add((row["event_id"], f"{row['home']} v {row['away']}"))

    settled_comparisons = []
    seen_events = set()
    for l in all_legs:
        if l.get("status") in ("won", "lost", "void"):
            eid = l.get("event_id")
            res_val = res.get(eid)
            score_str = f"{res_val[0] + res_val[2]} - {res_val[1] + res_val[3]} (HT {res_val[0]} - {res_val[1]})" if res_val else None
            prob = l.get("prob")
            settled_comparisons.append({
                "match": l.get("match", ""),
                "market": l.get("market", ""),
                "pick": l.get("pick", ""),
                "odds": l.get("odds", 0),
                "prob": prob,
                "status": l.get("status"),
                "score": score_str,
                "start_ms": l.get("start_ms") or 0,
                "source": "Saved Code"
            })
            if eid:
                seen_events.add(eid)

    finished_events = con.execute("""
        SELECT e.event_id, e.home, e.away, e.start_ms, r.h1, r.a1, r.h2, r.a2
        FROM events e
        JOIN results r ON r.event_id = e.event_id
        ORDER BY e.start_ms DESC LIMIT 50
    """).fetchall()
    for fe in finished_events:
        eid = fe["event_id"]
        if eid in seen_events:
            continue
        res_tuple = (fe["h1"], fe["a1"], fe["h2"], fe["a2"])
        score_str = f"{fe['h1'] + fe['h2']} - {fe['a1'] + fe['a2']} (HT {fe['h1']} - {fe['a1']})"
        match_name = f"{fe['home']} v {fe['away']}"
        top_picks = con.execute("""
            SELECT label, odds, prob, mid, spec, odesc FROM picks
            WHERE event_id = ? AND prob IS NOT NULL AND mid IN ('1', '18', '29', '10')
            ORDER BY prob DESC LIMIT 3
        """, (eid,)).fetchall()
        for p in top_picks:
            leg = {
                "market_id": p["mid"],
                "specifier": p["spec"] or "",
                "pick": p["odesc"] or p["label"].split(": ", 1)[-1],
                "match": match_name
            }
            st = settle.leg_status(leg, res_tuple)
            if st in ("won", "lost", "void"):
                settled_comparisons.append({
                    "match": match_name,
                    "market": p["label"].split(": ")[0] if ": " in p["label"] else "Market",
                    "pick": p["label"].split(": ", 1)[-1],
                    "odds": p["odds"],
                    "prob": p["prob"],
                    "status": st,
                    "score": score_str,
                    "start_ms": fe["start_ms"] or 0,
                    "source": "Imported Game"
                })

    settled_comparisons.sort(key=lambda x: x["start_ms"], reverse=True)
    decided = [c for c in settled_comparisons if c["status"] in ("won", "lost")]
    comp_stats = {
        "total": len(decided),
        "won": sum(1 for c in decided if c["status"] == "won"),
        "lost": sum(1 for c in decided if c["status"] == "lost"),
        "void": sum(1 for c in settled_comparisons if c["status"] == "void"),
        "win_rate": (sum(1 for c in decided if c["status"] == "won") / len(decided) * 100) if decided else 0,
        "avg_prob": (sum(c["prob"] for c in decided if c["prob"]) / len(decided) * 100) if decided else 0,
    }

    hub = {c["code"]: c for c in store.codes(con) if c.get("source") == "hub"}
    need_manual = [(c, l) for c, s in settled.items() for l in s["legs"] if l["status"] == "manual" and started(l)
                   and (c in played or c not in hub)]
    need_manual.sort(key=lambda cl: (cl[0] not in played, cl[1].get("start_ms") or 0))

    return render_template(
        "results/settlement.html",
        need_score=len(need_score),
        score_snippet=snippets.events_snippet(sorted(need_score)[:40]) if need_score else None,
        need_manual=need_manual[:100],
        n_manual=len(need_manual),
        settled_comparisons=settled_comparisons,
        comp_stats=comp_stats,
        msgs=msgs
    )


@bp.post("/bankroll")
def set_bankroll():
    con = get_db()
    b = _money(request.form.get("bankroll"))
    try:
        kf = float(request.form.get("fraction") or 0.25)
        kf = min(max(kf, 0.05), 1.0)
    except ValueError:
        kf = 0.25
    store.save_settings(con, bankroll=b, kelly_fraction=kf)
    return redirect(url_for("results.index"))


@bp.post("/bet")
def add_bet():
    con = get_db()
    code = (request.form.get("code") or "").upper()
    stake = _money(request.form.get("stake"))
    if not code or not stake:
        return index(msgs=[(False, "Choose a code and enter the stake.")])
    store.add_bet(con, code, stake)
    msgs = [(True, f"Recorded {stake:g} on {code}.")]
    limit = store.settings(con).get("monthly_limit")
    if limit:
        m = settle.money(store.bets(con), {}, {}, now_ms())
        if m["this_month"]["staked"] > limit:
            msgs.append((False, f"This month you've now staked {m['this_month']['staked']:g}, over your own limit "
                                f"of {limit:g}."))
    if request.form.get("back"):
        return redirect(back_to(request.form["back"], url_for("results.index")))
    return index(msgs=msgs)


@bp.post("/bet/<int:bet_id>")
def edit_bet(bet_id):
    con = get_db()
    action = request.form.get("action")
    if action == "delete":
        store.delete_bet(con, bet_id)
    elif action == "recalc":
        store.set_payout(con, bet_id, None)
    else:
        p = _money(request.form.get("payout"))
        if p is not None:
            store.set_payout(con, bet_id, p)
    return redirect(url_for("results.index"))


@bp.post("/leg")
def set_leg():
    store.set_leg_result(get_db(), request.form["code"], request.form["sel_key"], request.form.get("status"))
    return redirect(back_to(request.form.get("back"), url_for("results.index")))


@bp.post("/clear")
def clear_record():
    if request.form.get("confirm", "").strip().upper() != "DELETE":
        return index(msgs=[(False, 'Nothing deleted. Type DELETE in the box to confirm.')])
    n = store.delete_bet_record(get_db())
    return index(msgs=[(True, f"Deleted your bet record ({n} bet{'s' if n != 1 else ''}), every leg marked by hand and the Code Hub track record.")])


@bp.post("/limit")
def set_limit():
    store.save_settings(get_db(), monthly_limit=_money(request.form.get("limit")))
    return redirect(url_for("results.index"))
