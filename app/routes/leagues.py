"""Section 2: leagues. Every game in the leagues and dates the user picks, with one pick per game."""
from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from . import day_range, now_ms, num
from .. import store
from ..analysis import markets, picks
from ..analysis import flow
from ..analysis import target as reach
from ..db import get_db
from ..sources.sportybet import parse, snippets

bp = Blueprint("leagues", __name__, url_prefix="/leagues")


@bp.get("/")
def index():
    if request.args.get("mode") == "screen":
        return screen()
    con = get_db()
    imported = store.imported_leagues(con)
    start, end, start_ms, end_ms = day_range(request.args)
    chosen = request.args.getlist("tid") or [l["tournament_id"] for l in imported]
    fams = [f for f in request.args.getlist("fam") if f in markets.FAMILIES] or ["goals"]
    z = request.args.get("zone", "low")
    lo, hi = picks.zone_range(z) or (num(request.args, "mino", 1.0), num(request.args, "maxo", 1000.0))
    f = {"minp": num(request.args, "minp", 0), "maxp": num(request.args, "maxp", 100),
         "by": "return" if request.args.get("by") == "return" else "prob",
         "upcoming": request.args.get("upcoming", "1" if not request.args else "") == "1"}
    blocked = store.banned_ids(con)
    now = now_ms()
    goal = num(request.args, "todds", None)
    goal = min(max(goal, 1.01), 10000.0) if goal else None
    rows, scanned, no_pick, games = [], 0, 0, []
    listed = [g for g in store.list_events(con, start_ms, end_ms, chosen)
              if not (f["upcoming"] and (g["start_ms"] or 0) < now)]
    blocked |= store.ensure_picks(con, [g["event_id"] for g in listed])
    listed = [g for g in listed if g["event_id"] not in blocked]
    priced_by_game = store.load_picks(con, [g["event_id"] for g in listed], fams, f["minp"] / 100, f["maxp"] / 100,
                                      lo, hi)
    for g in listed:
        scanned += 1
        priced = priced_by_game[g["event_id"]]
        if goal:
            games.append(reach.from_priced(g["event_id"], f'{g["home"]} v {g["away"]}', priced,
                                           f["minp"] / 100, f["maxp"] / 100, lo, hi))
            for c in games[-1]:
                c.update(start_ms=g["start_ms"], tournament=g["tournament"])
        bp_ = picks.best_pick(None, fams, f["minp"] / 100, f["maxp"] / 100, lo, hi, f["by"], priced=priced)
        if not bp_:
            no_pick += 1
            continue
        rows.append({**{k: g[k] for k in ("event_id", "home", "away", "tournament", "start_ms", "saved_at",
                                         "n_markets")}, **bp_})
    # with a target, the code is built most likely first (that fits the most picks); otherwise rank as asked
    target = num(request.args, "target", None)
    by_prob = f["by"] == "prob" or bool(target)
    rows.sort(key=lambda r: -(r["prob"] if by_prob else r["ret"]))
    picks.with_running_accumulator(rows)
    # target chance: keep adding picks while the code still wins at least this often
    code = None
    if target and rows:
        for r in rows:
            r["beyond"] = r["acc_prob"] * 100 < target - 1e-9
        n = sum(1 for r in rows if not r["beyond"])
        code = {"n": n, "target": target, "row": rows[n - 1] if n else None, "next": rows[n] if n < len(rows) else None}
    # target odds: the code that reaches them with the highest chance, next to stacking the most likely picks
    best = None
    if goal:
        legs = reach.best_for_odds(games, goal)
        legs = sorted(legs or [], key=lambda l: -l["prob"])
        best = {"goal": goal, "legs": legs, "t": reach.totals(legs),
                "stacked": reach.totals(reach.stack_safest(games, goal))}
    d, dir_saved = store.directory(con)
    top, cats = parse.parse_directory(d) if d else ([], [])
    new_ids = store.new_leagues(con) if d else set()
    new = [(c["name"], t) for c in cats for t in c.get("tournaments", []) if t["id"] in new_ids]
    return render_template("leagues/index.html", imported=imported, chosen=set(chosen), fams=fams,
                           all_fams=markets.MAIN_FAMILIES, zones=picks.ZONES, zone=z, f=f, rows=rows,
                           scanned=scanned, no_pick=no_pick, start=start, end=end, top=top, cats=cats,
                           target="" if target is None else f"{target:g}", code=code, best=best,
                           todds="" if goal is None else f"{goal:g}",
                           show_all_url=url_for("leagues.index", **{k: request.args.getlist(k) for k in request.args
                                                                    if k != "tid"}),
                           all_chosen=set(chosen) == {l["tournament_id"] for l in imported},
                           league_only=sum(1 for r in rows if r["n_markets"] < 100),
                           directory_snippet=snippets.directory_snippet(), has_directory=bool(d),
                           dir_saved=dir_saved, new_leagues=new, n_leagues=sum(len(c.get("tournaments", [])) for c in cats))


DEFAULT_BET = "team_goals|Over 0.5"
RANKS = {"prob": "highest chance", "margin": "smallest market margin", "odds": "highest odds"}


def screen():
    """Choose the bet, find the teams: every pick of the chosen bet types in the chosen games, with home and away
    versions of a team bet merged into one list of teams, and the highest-chance code for a target total odds."""
    from ..analysis import bettypes
    con = get_db()
    a = request.args
    imported = store.imported_leagues(con)
    start, end, start_ms, end_ms = day_range(a)
    chosen = a.getlist("tid") or [l["tournament_id"] for l in imported]
    sent = a.get("sent") == "1"                      # the form was submitted (unticked boxes then mean off)
    upcoming = a.get("upcoming") == "1" if sent else True
    one = a.get("one") == "1" if sent else True
    noconf = a.get("noconf") == "1" if sent else True
    side = a.get("side") if a.get("side") in ("home", "away") else ""
    mino, maxo = num(a, "mino", 1.0), num(a, "maxo", 1000.0)
    minp = min(max(num(a, "minp", 0.0), 0.0), 100.0)
    rank = a.get("rank") if a.get("rank") in RANKS else "prob"
    goal = num(a, "todds", None)
    goal = min(max(goal, 1.01), 10000.0) if goal else None
    try:
        max_legs = max(1, min(int(a.get("maxlegs") or 6), 50))
    except ValueError:
        max_legs = 6
    now = now_ms()
    games = [g for g in store.list_events(con, start_ms, end_ms, chosen) if not (upcoming and (g["start_ms"] or 0) < now)]
    blocked = store.banned_ids(con) | store.ensure_picks(con, [g["event_id"] for g in games])
    ids = [g["event_id"] for g in games if g["event_id"] not in blocked]

    # the bet types on offer in these games, by category
    types = store.bet_types(con, ids)
    have = {t["bkey"] for t in types}
    keys = [k for k in a.getlist("bt") if k in have] or ([DEFAULT_BET] if DEFAULT_BET in have and not sent else [])
    groups = []
    for cat, label in bettypes.CATS:
        ts = sorted((t for t in types if t["cat"] == cat), key=lambda t: bettypes.sort_key(t["bkey"]))
        if ts:
            groups.append({"cat": cat, "label": label, "types": ts, "n_on": sum(1 for t in ts if t["bkey"] in keys)})

    rows = store.screen_picks(con, ids, keys, mino, maxo)
    for r in rows:
        r["reliable"] = bool(r["prob_ok"])
        r["team"] = r["home"] if r["side"] == "home" else r["away"] if r["side"] == "away" else None
        r["opponent"] = r["away"] if r["side"] == "home" else r["home"] if r["side"] == "away" else None
        r["zone"] = picks.zone(r["odds"])
        r["sel"] = {"eventId": r["event_id"], "marketId": r["mid"], "specifier": r["spec"], "outcomeId": r["oid"]}
    if side:
        rows = [r for r in rows if r["side"] in (None, side)]
    if minp > 0:
        rows = [r for r in rows if r["reliable"] and r["prob"] * 100 >= minp - 1e-9]
    order = {"prob": lambda r: (not r["reliable"], -(r["prob"] if r["reliable"] else 0), -r["odds"]),
             "margin": lambda r: (r["mkt_kept"] is None, r["mkt_kept"] if r["mkt_kept"] is not None else 0, -r["odds"]),
             "odds": lambda r: (-r["odds"], not r["reliable"])}[rank]
    rows.sort(key=order)
    shown, dropped = _one_or_compatible(rows, one, noconf)

    # main feature: the highest-chance codes that reach the target total odds, one per number of selections
    combos, n_usable = [], 0
    if goal:
        per_game = {}
        for r in rows:
            if r["reliable"] and not r["push"]:
                per_game.setdefault(r["event_id"], []).append(r)
        n_usable = len(per_game)
        for k, legs in reach.best_by_legs(list(per_game.values()), goal, max_legs):
            legs = sorted(legs, key=lambda l: -l["prob"])
            combos.append({"k": k, "legs": legs, "t": reach.totals(legs)})
        combos.sort(key=lambda c: -c["t"]["prob"])
    return render_template("leagues/screen.html", imported=imported, chosen=set(chosen),
                           all_chosen=set(chosen) == {l["tournament_id"] for l in imported}, start=start, end=end,
                           upcoming=upcoming, one=one, noconf=noconf, side=side, mino=mino, maxo=maxo, minp=minp,
                           rank=rank, ranks=RANKS, goal=goal, max_legs=max_legs, groups=groups, keys=set(keys),
                           rows=shown, dropped=dropped, n_games=len(ids), combos=combos, n_usable=n_usable,
                           n_unreliable=sum(1 for r in shown if not r["reliable"]), zl=picks.ZONE_LABEL,
                           cat_label=bettypes.CAT_LABEL,
                           names={t["bkey"]: t["bname"] for t in types})


def _one_or_compatible(rows, one, noconf):
    """rows in rank order. one: keep only the first pick of each match. noconf: drop a pick that can't win together
    with a pick of the same match kept above it. Returns (kept rows, number dropped)."""
    if not one and not noconf:
        return rows, 0
    kept, by_game = [], {}
    for r in rows:
        mine = by_game.setdefault(r["event_id"], [])
        if one and mine:
            continue
        if noconf and mine:
            m = markets._masks(r["mid"], r["spec"], r["odesc"] or "", r["home"], r["away"])
            if m and any(o[0] == m[0] and not (o[2] & m[2]) for o in (x["_m"] for x in mine) if o):
                continue
            r["_m"] = m
        elif noconf:
            r["_m"] = markets._masks(r["mid"], r["spec"], r["odesc"] or "", r["home"], r["away"])
        mine.append(r)
        kept.append(r)
    return kept, len(rows) - len(kept)


@bp.get("/margins")
def margins():
    """Where SportyBet keeps least: the average margin by market and by league, over the saved games in the
    chosen dates and leagues, split by odds zone."""
    con = get_db()
    imported = store.imported_leagues(con)
    start, end, start_ms, end_ms = day_range(request.args, default_days=7)
    chosen = request.args.getlist("tid") or [l["tournament_id"] for l in imported]
    upcoming = request.args.get("upcoming", "1" if "start" not in request.args else "") == "1"
    now = now_ms()
    games = [g for g in store.list_events(con, start_ms, end_ms, chosen)
             if not (upcoming and (g["start_ms"] or 0) < now)]
    blocked = store.banned_ids(con) | store.ensure_picks(con, [g["event_id"] for g in games])
    ids = [g["event_id"] for g in games if g["event_id"] not in blocked]
    try:
        min_games = max(1, int(request.args.get("min") or 3))
    except ValueError:
        min_games = 3
    all_markets = store.margins(con, ids, "market")
    families = [f for f in markets.FAMILIES if any(r["family"] == f for r in all_markets)]
    by_market = [r for r in all_markets if r["games"] >= min_games]
    fam = request.args.get("fam") if request.args.get("fam") in markets.FAMILIES else None
    if fam:
        by_market = [r for r in by_market if r["family"] == fam]
    by_league = [r for r in store.margins(con, ids, "league") if r["family"] in markets.MAIN_FAMILIES]
    leagues = {}
    for r in by_league:
        lg = leagues.setdefault(r["tournament_id"], {"name": f'{r["category"] or ""} {r["tournament"] or ""}'.strip(),
                                                     "games": 0, "fams": {}})
        lg["games"] = max(lg["games"], r["games"])
        lg["fams"][r["family"]] = r

    # Target odds builder from lowest-margin markets
    goal = num(request.args, "goal", None) or num(request.args, "todds", None)
    built_slip = None
    if goal and ids:
        goal = min(max(goal, 1.01), 1000.0)
        target_fams = [fam] if fam else markets.FAMILIES
        priced_by_game = store.load_picks(con, ids, target_fams, minp=0.35, maxp=1.0, mino=1.10, maxo=10.0)
        game_pool = []
        for g in games:
            priced = priced_by_game.get(g["event_id"], {})
            if priced:
                low_margin_priced = {k: v for k, v in priced.items() if v.get("ret") is not None and v["ret"] >= 0.90}
                if low_margin_priced:
                    candidates = reach.from_priced(g["event_id"], f'{g["home"]} v {g["away"]}', low_margin_priced,
                                                   minp=0.35, maxp=1.0, mino=1.10, maxo=10.0)
                    for c in candidates:
                        c.update(start_ms=g.get("start_ms"), tournament=g.get("tournament"))
                    game_pool.append(candidates)
        if game_pool:
            opt = flow.optimize_pool(game_pool, target_odds=goal, min_chance=0.35)
            if opt.get("legs"):
                built_slip = opt

    return render_template("leagues/margins.html", by_market=by_market, leagues=sorted(
        leagues.values(), key=lambda l: (l["fams"].get("goals") or {}).get("kept", 1)), zones=picks.ZONES,
        n_games=len(ids), start=start, end=end, upcoming=upcoming, imported=imported, chosen=set(chosen),
        all_chosen=set(chosen) == {l["tournament_id"] for l in imported}, min_games=min_games, fam=fam,
        families=families, main_fams=markets.MAIN_FAMILIES,
        built_slip=built_slip, goal=goal)


@bp.get("/singles")
def singles():
    """Value Singles Scanner: Finds single-match picks where SportyBet takes the smallest cut (highest expected return),
    with Kelly stake sizing and safe alternatives, turning the focus from negative-EV accumulators to sharp singles."""
    con = get_db()
    imported = store.imported_leagues(con)
    start, end, start_ms, end_ms = day_range(request.args, default_days=7)
    chosen = request.args.getlist("tid") or [l["tournament_id"] for l in imported]
    upcoming = request.args.get("upcoming", "1" if "start" not in request.args else "") == "1"
    now = now_ms()
    games = [g for g in store.list_events(con, start_ms, end_ms, chosen)
             if not (upcoming and (g["start_ms"] or 0) < now)]
    blocked = store.banned_ids(con) | store.ensure_picks(con, [g["event_id"] for g in games])
    ids = [g["event_id"] for g in games if g["event_id"] not in blocked]

    mino = num(request.args, "mino", 1.15)
    maxo = num(request.args, "maxo", 10.0)
    minp = num(request.args, "minp", 50.0) / 100.0
    min_ret = num(request.args, "minret", 90.0) / 100.0
    fam = request.args.get("fam", "").strip()
    by = request.args.get("by", "prob").strip()
    dir_filter = request.args.get("dir", "no_unders").strip()
    one = request.args.get("one", "1") == "1"

    cfg = store.settings(con)
    bankroll = cfg.get("bankroll")
    rows = store.value_singles(con, ids, mino=mino, maxo=maxo, minp=minp, min_ret=min_ret,
                               family=fam or None, order_by=by, direction=dir_filter,
                               one_per_game=one, limit=100)
    for r in rows:
        r["sel"] = {"eventId": r["event_id"], "marketId": r["mid"], "specifier": r["spec"] or "", "outcomeId": r["oid"]}
        r["zone"] = picks.zone(r["odds"])
        r["margin"] = (1.0 - r["ret"]) * 100 if r.get("ret") is not None else None
        b = r["odds"]
        p = r["prob"]
        edge = (p * b) - 1.0
        r["edge"] = edge * 100.0
        r["kelly_q"] = max(0.0, (edge / (b - 1.0)) * 25.0) if edge > 0 and b > 1.0 else 0.0
        r["kelly_cash"] = (bankroll * (r["kelly_q"] / 100.0)) if bankroll and r["kelly_q"] > 0 else ((bankroll * 0.01) if bankroll else None)

    return render_template("leagues/singles.html", rows=rows, n_games=len(ids),
                           start=start, end=end, upcoming=upcoming, imported=imported, chosen=set(chosen),
                           all_chosen=set(chosen) == {l["tournament_id"] for l in imported},
                           mino=mino, maxo=maxo, minp=minp * 100.0, min_ret=min_ret * 100.0,
                           zones=picks.ZONES, bankroll=bankroll, fam=fam, by=by, dir=dir_filter, one=one,
                           show_all_url=url_for("leagues.singles", **{k: request.args.getlist(k) for k in request.args if k != "tid"}))


@bp.get("/parlay")
def parlay():
    """Custom Parlay Generation Suite:
    1. Target Odds Optimizer (Dynamic Knapsack)
    2. Time-Staggered Hedging Engine (Progressive Cash-out Timeline)
    3. Zone-Structured Engine (Anchor - Engine - Multiplier)
    4. Round-Robin & System Permutations (Loss-Resistant Bets)
    """
    con = get_db()
    imported = store.imported_leagues(con)
    start, end, start_ms, end_ms = day_range(request.args, default_days=7)
    chosen = request.args.getlist("tid") or [l["tournament_id"] for l in imported]
    upcoming = request.args.get("upcoming", "1" if "start" not in request.args else "") == "1"
    now = now_ms()
    games_raw = [g for g in store.list_events(con, start_ms, end_ms, chosen)
                 if not (upcoming and (g["start_ms"] or 0) < now)]
    blocked = store.banned_ids(con) | store.ensure_picks(con, [g["event_id"] for g in games_raw])
    games_raw = [g for g in games_raw if g["event_id"] not in blocked]
    ids = [g["event_id"] for g in games_raw]

    strat = request.args.get("strat", "target")
    if strat not in ("target", "staggered", "zone", "round_robin"):
        strat = "target"

    from ..analysis import flow, parlay_builder
    priced_by_game = store.load_picks(con, ids, markets.MAIN_FAMILIES, minp=0.15, maxp=1.0, mino=1.10, maxo=10.0)
    dir_filter = request.args.get("dir", "no_unders").strip()
    game_pool = []
    for g in games_raw:
        priced = priced_by_game.get(g["event_id"], {})
        if priced:
            candidates = reach.from_priced(g["event_id"], f'{g["home"]} v {g["away"]}', priced,
                                           minp=0.15, maxp=1.0, mino=1.10, maxo=10.0)
            if dir_filter == "no_extreme_under":
                candidates = [c for c in candidates if not any(x in c["label"] for x in ("Under 4", "Under 5", "Under 6"))]
            elif dir_filter == "no_unders":
                candidates = [c for c in candidates if "Under" not in c["label"]]
            elif dir_filter == "over":
                candidates = [c for c in candidates if "Over" in c["label"] or "Under" not in c["label"]]
            for c in candidates:
                c.update(start_ms=g.get("start_ms"), tournament=g.get("tournament"))
            if candidates:
                game_pool.append([flow.normalize_candidate(c) for c in candidates])

    target_odds = min(max(num(request.args, "target_odds", 3.50), 1.05), 1000.0)
    min_legs = max(1, min(int(num(request.args, "min_legs", 2)), 20))
    max_legs = max(min_legs, min(int(num(request.args, "max_legs", 8)), 30))
    min_chance = min(max(num(request.args, "min_chance", 50.0), 5.0), 95.0) / 100.0

    n_legs = max(2, min(int(num(request.args, "n_legs", 4)), 10))
    min_gap = max(60, min(int(num(request.args, "min_gap", 105)), 720))

    preset_key = request.args.get("preset", "anchor_engine")

    pool_size = max(3, min(int(num(request.args, "pool_size", 5)), 8))
    fold_size = max(2, min(int(num(request.args, "fold_size", 3)), pool_size - 1))
    unit_stake = max(1.0, num(request.args, "unit_stake", 10.0))

    if strat == "target":
        result = parlay_builder.build_target_odds(game_pool, target_odds=target_odds,
                                                  min_legs=min_legs, max_legs=max_legs,
                                                  min_chance=min_chance)
    elif strat == "staggered":
        result = parlay_builder.build_time_staggered(game_pool, n_legs=n_legs, min_gap_mins=min_gap, min_chance=min_chance)
    elif strat == "zone":
        result = parlay_builder.build_zone_structured(game_pool, preset_key=preset_key)
    elif strat == "round_robin":
        result = parlay_builder.build_round_robin(game_pool, pool_size=pool_size, fold_size=fold_size,
                                                  unit_stake=unit_stake, min_chance=min_chance)

    return render_template("leagues/parlay.html", strat=strat, result=result,
                           presets=parlay_builder.PRESETS, preset_key=preset_key,
                           target_odds=target_odds, min_legs=min_legs, max_legs=max_legs,
                           min_chance=min_chance * 100.0, n_legs=n_legs, min_gap=min_gap,
                           pool_size=pool_size, fold_size=fold_size, unit_stake=unit_stake,
                           n_games=len(ids), start=start, end=end, upcoming=upcoming,
                           imported=imported, chosen=set(chosen), dir=dir_filter,
                           all_chosen=set(chosen) == {l["tournament_id"] for l in imported},
                           zones=picks.ZONES,
                           show_all_url=url_for("leagues.parlay", **{k: request.args.getlist(k) for k in request.args if k != "tid"}))


def _ticked(con, tids):
    """[(tournament id, 'Country League')] for the ticked leagues, named from the league list."""
    d, _ = store.directory(con)
    names = {}
    if d:
        for c in parse.parse_directory(d)[1]:
            for t in c.get("tournaments", []):
                names[t["id"]] = f'{c["name"]} {t["name"]}'
    return [(t, names.get(t, t)) for t in dict.fromkeys(tids) if t]


@bp.get("/fetch")
def fetch():
    """Console code for the ticked leagues: the fallback when the CodeMatch button can't be used."""
    leagues = _ticked(get_db(), request.args.getlist("tid"))
    return render_template("leagues/fetch.html", leagues=leagues,
                           snippet=snippets.leagues_snippet(leagues) if leagues else None)


@bp.post("/queue")
def queue():
    """Queue the ticked leagues for the CodeMatch button, straight from the league picker."""
    from .bridge import make_job
    con = get_db()
    leagues = _ticked(con, request.form.getlist("tid"))
    if not leagues:
        return jsonify(error="Tick at least one league first."), 400
    snip = snippets.leagues_snippet(leagues)
    label = leagues[0][1] if len(leagues) == 1 else f"{len(leagues)} leagues"
    job = make_job(con, label, snip.requests)
    return jsonify(id=job["id"], n=len(job["requests"]))


@bp.post("/directory/queue")
def queue_directory():
    """Fetch the league list again with the CodeMatch button, so leagues and tournaments added on SportyBet since
    the last fetch can be ticked."""
    from .bridge import make_job
    job = make_job(get_db(), "the league list", snippets.directory_snippet().requests)
    return jsonify(id=job["id"], n=len(job["requests"]))


@bp.post("/delete")
def delete():
    store.delete_league(get_db(), request.form.get("tid", ""))
    return redirect(url_for("leagues.index"))


@bp.get("/<path:tid>")
def league(tid):
    con = get_db()
    games = store.list_events(con, tournament_ids=[tid])
    blocked = store.banned_ids(con) | store.ensure_picks(con, [g["event_id"] for g in games])
    games = [g for g in games if g["event_id"] not in blocked]
    now = now_ms()
    upcoming = [g for g in games if (g["start_ms"] or 0) >= now]
    ids = [g["event_id"] for g in games]
    priced = store.load_picks(con, ids, ["goals"])
    present = store.families_of(con, ids)
    for g in games:
        g.update(picks.headline(None, priced[g["event_id"]]),
                 fams={f: f in present.get(g["event_id"], ()) for f in markets.FAMILIES})
    name = games[0]["tournament"] if games else tid
    if games and games[0].get("category"):
        name = f'{games[0]["category"]} {name}'
    partial = [(g["event_id"], f'{g["home"]} v {g["away"]}') for g in upcoming if g["n_markets"] < 100]
    return render_template("leagues/league.html", tid=tid, name=name, games=games, n_upcoming=len(upcoming),
                           league_snippet=snippets.leagues_snippet([(tid, name)]),
                           games_snippet=snippets.events_snippet(partial) if partial else None, n_partial=len(partial),
                           saved=max((g["saved_at"] for g in games), default=None))
