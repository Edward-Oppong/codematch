"""Section 3: games. Every market in one game, and the safer / riskier picks around any of them."""
from flask import Blueprint, redirect, render_template, request, url_for

from . import back_to, day_range, now_ms, num
from .. import store
from ..analysis import markets, picks
from ..analysis.alternatives import alternatives
from ..db import get_db
from ..sources.sportybet import parse, snippets

bp = Blueprint("games", __name__, url_prefix="/games")


@bp.get("/")
def index():
    con = get_db()
    start, end, start_ms, end_ms = day_range(request.args, default_days=7)
    q = (request.args.get("q") or "").strip()
    leagues = store.imported_leagues(con)
    tids = [t for t in request.args.getlist("tid") if t]
    games = store.list_events(con, start_ms, end_ms, tournament_ids=tids or None, q=q or None)
    partial = [(g["event_id"], f'{g["home"]} v {g["away"]}') for g in games if g["n_markets"] < 100]
    
    # Finished games waiting for final scores
    from ..analysis import settle
    results_map = store.results(con)
    now = now_ms()
    finished_unsettled = [(g["event_id"], f'{g["home"]} v {g["away"]}') 
                          for g in games if (g["start_ms"] or 0) + settle.AFTER_KICKOFF_MS < now 
                          and g["event_id"] not in results_map]

    return render_template("games/index.html", games=games, start=start, end=end, q=q, leagues=leagues,
                           chosen=set(tids),
                           snippet=snippets.events_snippet(partial[:40]) if partial else None,
                           n_partial=len(partial),
                           finished_snippet=snippets.events_snippet(finished_unsettled[:40]) if finished_unsettled else None,
                           n_finished_unsettled=len(finished_unsettled),
                           results_map=results_map)


@bp.get("/steam")
def steam():
    """Odds Steam & Line Movement: Track sharp money momentum and price shortening across all saved games."""
    con = get_db()
    start, end, start_ms, end_ms = day_range(request.args, default_days=7)
    leagues = store.imported_leagues(con)
    tids = [t for t in request.args.getlist("tid") if t]
    q_team = (request.args.get("q") or "").strip()
    direction = request.args.get("dir", "steam")
    if direction not in ("steam", "drift", "all"):
        direction = "steam"
    min_pct = num(request.args, "minpct", 2.0)

    now = now_ms()
    upcoming = request.args.get("upcoming", "1" if "start" not in request.args else "") == "1"
    games = store.list_events(con, start_ms, end_ms, tournament_ids=tids or None, q=q_team or None)
    if upcoming:
        games = [g for g in games if (g["start_ms"] or 0) >= now]
    ids = [g["event_id"] for g in games]

    movers = store.steam_movers(con, ids, min_pct=min_pct, direction=direction, limit=100)
    for m in movers:
        m["sel"] = {"eventId": m["event_id"], "marketId": m["mid"], "specifier": m["spec"] or "", "outcomeId": m["oid"]}
        m["zone"] = picks.zone(m["odds"])
        m["prob_diff"] = (m["prob"] - (m["first_prob"] or m["prob"])) * 100.0 if m.get("prob") and m.get("first_prob") else None

    return render_template(
        "games/steam.html", movers=movers, start=start, end=end, leagues=leagues, chosen=set(tids),
        direction=direction, min_pct=min_pct, upcoming=upcoming, q=q_team,
        n_games=len(games), zones=picks.ZONES,
        show_all_url=url_for("games.steam", start=start.isoformat(), end=end.isoformat(), dir=direction, minpct=min_pct)
    )


@bp.post("/delete")
def delete():
    store.delete_event(get_db(), request.form.get("event_id", ""))
    return redirect(back_to(request.form.get("back"), url_for("games.index")))


@bp.get("/<path:event_id>")
def game(event_id):
    con = get_db()
    row = store.get_event(con, event_id)
    if row is None:
        return render_template("games/missing.html", event_id=event_id,
                               snippet=snippets.events_snippet([(event_id, event_id)])), 404
    ev, saved, n_markets = row
    info = parse.event_info(ev)
    present = markets.families_present(ev)
    fam = request.args.get("fam", "goals")
    if fam not in markets.FAMILIES and fam != "other":
        fam = "goals"
    others = markets.other_markets(ev)
    priced = markets.build_priced(ev, fam) if fam != "other" else {}
    minp, maxo = num(request.args, "minp", None), num(request.args, "maxo", None)
    z = request.args.get("zone", "")
    rows = [(k, v) for k, v in priced.items()
            if (minp is None or v["prob"] * 100 >= minp) and (maxo is None or v["odds"] <= maxo)
            and (not z or picks.zone(v["odds"]) == z)]
    rows.sort(key=lambda kv: -kv[1]["prob"])
    pick = request.args.get("pick")
    safer = riskier = base = None
    if pick in priced:
        base = priced[pick]
        safer, riskier = alternatives(priced, pick)
    else:
        pick = None
    zone_counts = {k: sum(1 for v in priced.values() if picks.zone(v["odds"]) == k) for k, *_ in picks.ZONES}
    first = store.first_prices(con, event_id)
    history = store.price_history(con, event_id, pick) if pick else []
    movers = sorted(((k, first[k], v["odds"]) for k, v in priced.items() if first.get(k) and first[k] != v["odds"]),
                    key=lambda m: -abs(m[2] / m[1] - 1))[:8]
    from ..analysis import settle
    result = store.results(con).get(event_id)
    return render_template(
        "games/game.html", info=info, ev=ev, saved=saved, n_markets=n_markets, present=present, fam=fam,
        fams=list(markets.FAMILIES), rows=rows[:300], n_rows=len(rows), pick=pick, base=base, safer=safer or [],
        riskier=riskier or [], minp="" if minp is None else f"{minp:g}", maxo="" if maxo is None else f"{maxo:g}",
        zone=z, zones=picks.ZONES, zone_counts=zone_counts, zone_of=picks.zone, zone_label=picks.ZONE_LABEL,
        first=first, sb_url=parse.match_url(ev, info), history=history, spark=sparkline(history), movers=movers,
        others=others, other_view=other_view(others, request.args), q=request.args.get("q", ""),
        group=request.args.get("group") or ("Timing and order" if any(o["group"] == "Timing and order" for o in others) else ""),
        fam_label=lambda f: f.capitalize(),
        started=(info["start_ms"] or 0) < now_ms(),
        result=result,
        leg_status=settle.leg_status,
        snippet=snippets.events_snippet([(event_id, f'{info["home"]} v {info["away"]}')]))


def sparkline(history, w=280, h=60, pad=6):
    """SVG points for a pick's odds over time, or None with fewer than two prices."""
    if len(history) < 2:
        return None
    ts = [x["ts"] for x in history]
    od = [x["odds"] for x in history]
    t0, t1 = min(ts), max(ts)
    lo, hi = min(od), max(od)
    span_t, span_o = (t1 - t0) or 1, (hi - lo) or 1
    pts = [(pad + (t - t0) / span_t * (w - 2 * pad), h - pad - (o - lo) / span_o * (h - 2 * pad)) for t, o in zip(ts, od)]
    # odds stay flat between imports, so draw steps rather than slopes
    path = [f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        path.append(f"H{x1:.1f}V{y1:.1f}")
    return {"w": w, "h": h, "d": "".join(path), "last": pts[-1], "lo": lo, "hi": hi}


def other_view(others, args, limit=50):
    """One group of unmodelled markets at a time, optionally filtered by text (a player's name), at most `limit`."""
    from collections import Counter
    counts = Counter(o["group"] for o in others)
    group = args.get("group") or ("Timing and order" if counts.get("Timing and order") else next(iter(counts), ""))
    q = (args.get("q") or "").strip().lower()
    hits = [o for o in others if o["group"] == group and
            (not q or q in o["market"].lower() or any(q in r["desc"].lower() for r in o["outcomes"]))]
    return {"groups": sorted(counts.items()), "group": group, "markets": hits[:limit], "n": len(hits), "limit": limit}
