"""Section 1: booking codes. Fetch them in the browser, then review each one against its games."""
import re

from flask import Blueprint, redirect, render_template, request, url_for

from .. import store
from ..analysis import codes as review
from ..analysis import compare
from ..analysis.picks import ZONE_LABEL, zone
from ..db import get_db
from ..sources.sportybet import snippets

bp = Blueprint("codes", __name__)
CODE_RE = re.compile(r"^[A-Za-z0-9]{4,12}$")
MAX_LEGS = 50                 # SportyBet takes at most this many picks in one code


SORTS = {   # how the saved codes can be ordered; None values go last
    "ret": ("exp_return", True), "chance": ("joint_prob", True), "odds": ("total_odds", False),
    "popular": ("popularity", True), "kickoff": ("first", False)}
HUB_KEEP_DAYS = 30           # finished Code Hub codes stay this long for the track record on Results


def _best_built(rows, legs_by_code, get_event, goal):
    """The highest-chance code for these odds built from what the open codes picked (one pick per game)."""
    from ..analysis import consensus, flow
    open_rows = [r for r in rows if r.get("open")]
    if len(open_rows) < 2:
        return None
    # Fast consensus over top 25 most popular/highest return open codes
    top_open = sorted(open_rows, key=lambda r: (-(r.get("popularity") or 0), -(r.get("exp_return") or 0)))[:25]
    open_codes = {r["code"]: legs_by_code[r["code"]] for r in top_open if r["code"] in legs_by_code}
    fx = consensus.fixtures(open_codes, get_event, 2)
    games = [[flow.normalize_candidate(c) for c in consensus.candidates(f)] for f in fx]
    opt = flow.optimize_pool(games, target_odds=goal)
    legs = opt["legs"]
    return {"legs": legs, "t": opt["totals"], "goal": goal, "n_fixtures": len(fx)} if legs else None


_LAST_HUB_CLEANUP_MS = 0
HUB_CLEANUP_INTERVAL_MS = 10 * 60 * 1000  # run maintenance at most once every 10 minutes on GET /


def _index(snippet=None, msgs=(), hub_snippet=None):
    global _LAST_HUB_CLEANUP_MS
    import sqlite3
    from . import num, now_ms
    from ..analysis.settle import AFTER_KICKOFF_MS
    con = get_db()
    now = now_ms()
    
    from flask import current_app
    is_testing = current_app.config.get("TESTING", False)
    # Throttle hub recording and purging so it never blocks page rendering or locks the DB
    if is_testing or (now - _LAST_HUB_CLEANUP_MS > HUB_CLEANUP_INTERVAL_MS):
        try:
            from .results import record_hub
            record_hub(con)
            store.purge_old_hub(con, now - HUB_KEEP_DAYS * 86400 * 1000)
            _LAST_HUB_CLEANUP_MS = now
        except sqlite3.OperationalError:
            pass

    rows, cache = [], {}
    get_event = lambda eid: cache.setdefault(("ev", eid), (store.get_event(con, eid) or (None,))[0])
    src = request.args.get("src", "all")
    src = src if src in ("all", "hub", "mine") else "all"
    sort = request.args.get("sort", "ret")
    sort = sort if sort in SORTS else "ret"
    open_only = request.args.get("open") == "1"
    hide_toxic = request.args.get("hide_toxic") == "1"
    goal = min(max(num(request.args, "goal", store.settings(con).get("usual_odds") or 3.0), 1.01), 10000.0)
    if request.args.get("goal"):
        try:
            store.save_settings(con, usual_odds=goal)
        except sqlite3.OperationalError:
            pass

    # Bulk load all legs in one single indexed query (avoids 600+ sequential round trips)
    legs_by_code = store.load_all_legs(con)
    all_codes = store.codes(con)

    for c in all_codes:
        legs = legs_by_code.get(c["code"], [])
        s = review.summarise(legs)
        weak = s["weakest"][0] if s["weakest"] else None
        rows.append({**c, **s, "open": (s["first"] or 0) >= now,
                     "finished": bool(s["last"]) and s["last"] + AFTER_KICKOFF_MS < now,
                     "keeps": 1 - s["exp_return"] if s["exp_return"] is not None else None,
                     "weak": weak})
    # finished Code Hub codes leave the list; they're kept a while for the track record on Results
    listed = [r for r in rows if not (r.get("source") == "hub" and r["finished"])]
    shown = [r for r in listed if src == "all" or (r.get("source") == "hub") == (src == "hub")]
    if open_only:
        shown = [r for r in shown if r["open"]]
    if hide_toxic:
        shown = [r for r in shown if r.get("toxicity_grade") not in ("D", "F")]
    key, desc = SORTS[sort]
    have = [r for r in shown if r.get(key) is not None]
    shown = sorted(have, key=lambda r: r[key], reverse=desc) + [r for r in shown if r.get(key) is None]
    best = sorted((r for r in listed if r["open"] and r["exp_return"] is not None
                   and (not hide_toxic or r.get("toxicity_grade") not in ("D", "F"))),
                  key=lambda r: -r["exp_return"])[:3]
    built = _best_built(listed, legs_by_code, get_event, goal)
    pairs = compare.compare_pairs({r["code"]: legs_by_code[r["code"]] for r in listed}) if len(listed) <= 60 else []
    return render_template("codes/index.html", rows=listed, shown=shown, pairs=pairs[:10], n_pairs=len(pairs),
                           src=src, sort=sort, open_only=open_only, hide_toxic=hide_toxic, best=best, built=built, goal=goal,
                           n_hub=sum(1 for r in listed if r.get("source") == "hub"),
                           n_hub_done=sum(1 for r in rows if r.get("source") == "hub" and r["finished"]),
                           hub_snippet=hub_snippet, too_many_to_pair=len(listed) > 60, keep_days=HUB_KEEP_DAYS,
                           has_directory=store.directory(con)[0] is not None, n_games=store.counts(con)["games"],
                           snippet=snippet, msgs=msgs)


@bp.get("/")
def index():
    return _index()


@bp.route("/codes/batch-surgeon", methods=["GET", "POST"])
def batch_surgeon():
    """Batch Code Surgeon: Audits all open codes at once, identifies toxic/low-chance legs,
    and automatically swaps them for safer, higher-probability alternative picks from the same games.
    Allows punters to upgrade their entire code portfolio in a single click without opening each fixture."""
    con = get_db()
    cache = {}
    get_event = lambda eid: cache.setdefault(("ev", eid), (store.get_event(con, eid) or (None,))[0])
    priced_for = review.priced_lookup(get_event, cache)

    from . import now_ms
    now = now_ms()
    all_codes = store.codes(con)
    legs_by_code = store.load_all_legs(con)

    try:
        min_odds = float(request.args.get("mino", 1.12))
    except ValueError:
        min_odds = 1.12

    target_code = request.args.get("code")
    selected_codes = request.form.getlist("code") or ([target_code.upper()] if target_code else None)

    surgeries = []
    total_toxic_cured = 0

    for c in all_codes:
        code_str = c["code"]
        if selected_codes and code_str not in selected_codes:
            continue

        legs = legs_by_code.get(code_str, [])
        if not legs:
            continue

        s_orig = review.summarise(legs, priced_for)
        # Skip finished codes only if upcoming=1 filter is passed
        if request.args.get("upcoming") == "1" and s_orig["last"] and s_orig["last"] < now and not target_code:
            continue

        contexts = [review.leg_context(get_event, l, cache) for l in legs]
        legs_with_odds, _ = review.with_game_odds(zip(legs, contexts))

        # Run the surgeon: swap any leg where a safer alternative exists
        improved_legs = review.improve(legs_with_odds, contexts, swap=True, min_odds=min_odds)
        n_swapped = sum(1 for l in improved_legs if l.get("changed"))
        total_toxic_cured += n_swapped

        s_improved = review.summarise(improved_legs, priced_for)

        # Build list of specific leg changes
        changes = []
        for orig, imp, ctx in zip(legs, improved_legs, contexts):
            is_toxic = (orig.get("ret") or 0) < 0.91 or (orig.get("prob") or 0) < 0.50
            if imp.get("changed"):
                changes.append({
                    "match": orig.get("match", ""),
                    "was": imp.get("was", orig.get("pick", "")),
                    "was_odds": orig.get("odds", 0),
                    "was_prob": orig.get("prob"),
                    "now": imp.get("label", ""),
                    "now_odds": imp.get("odds", 0),
                    "now_prob": imp.get("prob"),
                    "boost": round(((imp.get("prob") or 0) - (orig.get("prob") or 0)) * 100, 1),
                    "toxic": is_toxic
                })

        surgeries.append({
            "code": code_str,
            "source": c.get("source"),
            "popularity": c.get("popularity"),
            "n_legs": len(legs),
            "n_swapped": n_swapped,
            "orig": s_orig,
            "improved": s_improved,
            "legs": improved_legs,
            "changes": changes,
            "has_data": any(ctx.get("has_data") for ctx in contexts),
            "chance_boost": round(((s_improved.get("joint_prob") or 0) - (s_orig.get("joint_prob") or 0)) * 100, 1)
                            if s_improved.get("joint_prob") and s_orig.get("joint_prob") else None,
            "selections": [
                {"eventId": l["event_id"], "marketId": l.get("market_id"),
                 "specifier": l.get("specifier") or "", "outcomeId": l.get("outcome_id")}
                for l in improved_legs if l.get("market_id") and l.get("outcome_id")
            ]
        })

    # Sort surgeries by highest number of improvements or highest toxicity margin
    surgeries.sort(key=lambda s: (-s["n_swapped"], -(s["orig"].get("toxicity_margin_pct") or 0)))

    return render_template("codes/surgeon.html", surgeries=surgeries,
                           total_toxic_cured=total_toxic_cured, min_odds=min_odds,
                           total_scanned=len(surgeries), target_code=target_code)


@bp.post("/codes/fetch")
def fetch():
    """Turn the codes the user typed into console code that fetches them in their browser."""
    raw = [c.strip().upper() for c in re.split(r"[\s,;]+", request.form.get("codes", "")) if c.strip()]
    good = list(dict.fromkeys(c for c in raw if CODE_RE.match(c)))
    msgs = [(False, f"{c}: not a valid code format") for c in raw if not CODE_RE.match(c)]
    if not good:
        return _index(msgs=msgs or [(False, "Paste at least one booking code.")])
    have = {c["code"] for c in store.codes(get_db())}
    again = [c for c in good if c in have]
    if again:
        msgs.append((True, f"Already saved, fetching again to refresh: {', '.join(again)}"))
    return _index(snippet=snippets.codes_snippet(good), msgs=msgs)


def _hub_snippet(f):
    from . import num
    days = int(num(f, "days", 3))
    pages = int(num(f, "pages", 3))
    lo, hi = num(f, "omin", None), num(f, "omax", None)
    lmin, lmax = int(num(f, "lmin", 1)), int(num(f, "lmax", MAX_LEGS))
    lmin, lmax = max(1, min(lmin, MAX_LEGS)), max(1, min(lmax, MAX_LEGS))
    return snippets.hub_snippet(days=days, pages=pages, odds=(lo, hi), legs=(min(lmin, lmax), max(lmin, lmax)))


def _index_hub(hub_snippet=None, msgs=()):
    con = get_db()
    from . import num, now_ms
    from ..analysis.settle import AFTER_KICKOFF_MS
    now = now_ms()
    rows, cache = [], {}
    get_event = lambda eid: cache.setdefault(("ev", eid), (store.get_event(con, eid) or (None,))[0])
    sort = request.args.get("sort", "popular")
    sort = sort if sort in SORTS else "popular"
    hide_toxic = request.args.get("hide_toxic") == "1"
    goal = min(max(num(request.args, "goal", store.settings(con).get("usual_odds") or 3.0), 1.01), 10000.0)

    legs_by_code = store.load_all_legs(con)
    all_codes = store.codes(con)
    for c in all_codes:
        if c.get("source") != "hub":
            continue
        legs = legs_by_code.get(c["code"], [])
        s = review.summarise(legs)
        weak = s["weakest"][0] if s["weakest"] else None
        rows.append({**c, **s, "open": (s["first"] or 0) >= now,
                     "finished": bool(s["last"]) and s["last"] + AFTER_KICKOFF_MS < now,
                     "keeps": 1 - s["exp_return"] if s["exp_return"] is not None else None,
                     "weak": weak})
    listed = [r for r in rows if not r["finished"]]
    if hide_toxic:
        listed = [r for r in listed if r.get("toxicity_grade") not in ("D", "F")]
    key, desc = SORTS[sort]
    have = [r for r in listed if r.get(key) is not None]
    shown = sorted(have, key=lambda r: r[key], reverse=desc) + [r for r in listed if r.get(key) is None]
    best = sorted((r for r in listed if r["open"] and r["exp_return"] is not None
                   and (not hide_toxic or r.get("toxicity_grade") not in ("D", "F"))),
                  key=lambda r: -r["exp_return"])[:3]
    built = _best_built(listed, legs_by_code, get_event, goal)
    return render_template("codes/hub.html", shown=shown, best=best, built=built, sort=sort, goal=goal,
                           hide_toxic=hide_toxic, hub_snippet=hub_snippet, msgs=msgs)


@bp.route("/codes/hub", methods=["GET", "POST"])
def hub():
    """Code Hub: trending community codes, best right now, and consensus generator."""
    if request.method == "POST":
        return _index(hub_snippet=_hub_snippet(request.form))
    return _index_hub()


@bp.post("/codes/hub/queue")
def hub_queue():
    """Queue the Code Hub fetch for the CodeMatch button. With 'games' ticked, the games in the codes are fetched
    in the same trip once the list arrives, so every leg can be compared with the rest of its game."""
    from flask import jsonify
    from .bridge import make_job
    snip = _hub_snippet(request.form)
    job = make_job(get_db(), "Code Hub", snip.requests,
                   follow="hub_games" if request.form.get("games") == "1" else None)
    return jsonify(id=job["id"], n=len(job["requests"]))


@bp.get("/code/<code>")
def review_code(code):
    con = get_db()
    code = code.upper()
    legs = store.load_legs(con, code)
    if not legs:
        return redirect(url_for("codes.index"))
    cache = {}
    get_event = lambda eid: (store.get_event(con, eid) or (None,))[0]
    contexts = [review.leg_context(get_event, l, cache) for l in legs]
    legs, unresolved = review.with_game_odds(zip(legs, contexts))
    # results so far: settled from final scores, or marked by hand
    from ..analysis import settle
    from . import now_ms
    res, manual, now = store.results(con), store.manual_results(con), now_ms()
    ctx = []
    for l, c in zip(legs, contexts):
        mark = manual.get((code, l["sel_key"]))
        status = settle.leg_status(l, res.get(l["event_id"]), mark)
        played = (l.get("start_ms") or 0) + settle.AFTER_KICKOFF_MS < now
        ctx.append({"leg": l, "ctx": c, "zone": zone(l["odds"]), "status": status, "marked": bool(mark),
                    "played": played})
    statuses = [r["status"] for r in ctx]
    outcome = None
    if any(s_ in ("won", "lost", "void") for s_ in statuses):
        outcome = {"won": statuses.count("won"), "lost": statuses.count("lost"), "void": statuses.count("void"),
                   "open": sum(1 for s_ in statuses if s_ in ("pending", "manual")),
                   "code": settle.code_status(statuses)}
    k = 5 if len(legs) > 10 else (2 if len(legs) > 4 else 0)
    missing = [(r["leg"]["event_id"], r["leg"]["match"]) for r in ctx if r["ctx"].get("why") == "game not imported"]
    # "raise the chance" tool
    try:
        keep = int(request.args.get("keep") or 0) or None
        min_odds = float(request.args.get("mino") or 1.10)
    except ValueError:
        keep, min_odds = None, 1.10
    swap = request.args.get("swap") == "1"
    priced_for = review.priced_lookup(get_event, cache)
    better = None
    if keep or swap:
        new = review.improve(legs, contexts, keep=keep, swap=swap, min_odds=min_odds)
        better = {"legs": new, "s": review.summarise(new, priced_for), "n_swapped": sum(l["changed"] for l in new)}
    s_ = review.summarise(legs, priced_for)
    reach = _reach(legs, contexts, priced_for, request.args.get("todds"), s_, request.args.get("minp"))
    cfg = store.settings(con)
    return render_template("codes/review.html", code=code, s=s_, legs=ctx, k=k, reach=reach,
                           unresolved=unresolved, better=better, outcome=outcome, keep=keep or "", swap=swap, min_odds=min_odds,
                           n_with_data=sum(1 for c in contexts if c.get("has_data")),
                           drop=review.drop_weakest(legs, k) if k else None, zone_label=ZONE_LABEL,
                           bankroll=cfg.get("bankroll"), kelly_fraction=cfg.get("kelly_fraction", 0.25),
                           missing=len(missing),
                           missing_snippet=snippets.events_snippet(list(dict.fromkeys(missing))) if missing else None)


def _min_chance(raw):
    """'Each leg at least this % chance' as a fraction, 0 when empty or not a number."""
    try:
        return min(max(float(raw), 0.0), 99.0) / 100 if raw else 0.0
    except ValueError:
        return 0.0


def _reach(legs, contexts, priced_for, raw, s, raw_minp=None):
    """The code's own games, any pick on them in the families the code uses, chosen to reach the asked odds with
    the highest chance. Games without imported odds can only keep the code's own leg."""
    from ..analysis import target
    try:
        goal = float(raw) if raw else None
    except ValueError:
        goal = None
    if not goal:
        return None
    goal = min(max(goal, 1.01), 10000.0)
    minp = _min_chance(raw_minp)
    by_game, own = {}, set()
    for l, c in zip(legs, contexts):
        by_game.setdefault(l["event_id"], []).append((l, c))
        if c.get("info"):
            own.add((l["event_id"], c["info"]["label"]))
    games = []
    for eid, items in by_game.items():
        fams = {c["family"] for _, c in items if c.get("has_data") and c.get("family")}
        cands = []
        for fam in fams:
            cands += target.from_priced(eid, items[0][0]["match"], priced_for(eid, fam) or {}, minp=minp)
        if not cands:                    # no odds for this game: only the code's own leg, if it stands alone
            if len(items) == 1 and items[0][0].get("prob") and not items[0][0].get("push_prob"):
                l = items[0][0]
                sel = {"eventId": eid, "marketId": l.get("market_id"), "specifier": l.get("specifier") or "",
                       "outcomeId": l.get("outcome_id")}
                cands = [{"event_id": eid, "match": l["match"], "label": f'{l["market"]}: {l["pick"]}',
                          "odds": l["odds"], "prob": l["prob"], "ret": l["odds"] * l["prob"], "zone": zone(l["odds"]),
                          "sel": sel if sel["marketId"] else None}]
        games.append([c for c in cands if c["prob"] >= minp])
    chosen = sorted(target.best_for_odds(games, goal) or [], key=lambda l: -l["prob"])
    for l in chosen:
        l["own"] = (l["event_id"], l["label"]) in own
    return {"goal": goal, "minp": minp, "legs": chosen, "t": target.totals(chosen), "n_games": len(games),
            "n_priced": sum(1 for g in games if len(g) > 1)}


@bp.get("/codes/fixtures")
def fixtures():
    """Games that appear in several codes, the picks each code made on them, and the safest of those picks."""
    from ..analysis import consensus, picks as picks_
    con = get_db()
    legs_by_code = {c["code"]: store.load_legs(con, c["code"]) for c in store.codes(con)}
    get_event = lambda eid: (store.get_event(con, eid) or (None,))[0]
    try:
        min_codes = max(2, int(request.args.get("min", 2)))
    except ValueError:
        min_codes = 2
    raw_n = (request.args.get("n") or "").strip()
    try:
        n = max(1, min(int(raw_n), MAX_LEGS)) if raw_n else None       # empty = every fixture, up to MAX_LEGS
    except ValueError:
        n = None
    use = request.args.get("use", "target")
    use = use if use in ("common", "target", "safest") else "target"
    try:
        goal = float(request.args.get("odds") or 2)
    except ValueError:
        goal = 2.0
    goal = min(max(goal, 1.01), 10000.0)
    agree_only = request.args.get("agree") == "1"
    minp = _min_chance(request.args.get("minp"))
    try:
        min_legs = max(1, min(int(request.args.get("minlegs") or 1), MAX_LEGS))
    except ValueError:
        min_legs = 1
    upcoming = request.args.get("all") != "1"
    rows = consensus.fixtures(legs_by_code, get_event, min_codes)
    days = None
    if upcoming:
        from . import now_ms
        rows = [f for f in rows if (f["start_ms"] or 0) >= now_ms()]
        # optional days (UTC, Ghana time), end day included
        if request.args.get("start") or request.args.get("end"):
            from . import day_range
            d0, d1, start_ms, end_ms = day_range(request.args, default_days=0)
            rows = [f for f in rows if start_ms <= (f["start_ms"] or 0) < end_ms]
            days = (d0, d1)
    pool = [f for f in rows if f["agree"]] if agree_only else rows
    stacked = None
    if use == "target":
        from ..analysis import flow
        pool = pool[:n] if n else pool               # the search can look at every fixture; the code stays short
        games = [[flow.normalize_candidate(c) for c in consensus.candidates(f) if c["prob"] >= minp] for f in pool]
        opt = flow.optimize_pool(games, target_odds=goal, min_legs=min_legs, min_chance=minp)
        legs = opt["legs"]
        stacked = opt["stacked"]
    else:
        legs = consensus.build_code(pool, use, n or MAX_LEGS)    # skips fixtures without a usable pick
    acc = picks_.accumulator(legs)
    if acc:
        import math
        acc["ret"] = math.prod(l["ret"] for l in legs)
    no_sel = sum(1 for l in legs if not l.get("sel"))
    # picks priced from the codes, not the game: how old those odds may be
    saved_at = {c["code"]: c["fetched_at"] for c in store.codes(con)}
    from_code = [l for l in legs if l.get("from_code")]
    oldest = min((saved_at[c] for l in from_code for c in l.get("codes", []) if c in saved_at), default=None)
    missing = [(f["event_id"], f["match"]) for f in rows if not f["imported"]]
    return render_template("codes/fixtures.html", rows=rows, n_codes=len(legs_by_code), min_codes=min_codes,
                           use=use, n=n or "", legs=legs, acc=acc, upcoming=upcoming, zone_label=ZONE_LABEL,
                           goal=goal, agree_only=agree_only, minp=minp, pool=len(pool), stacked=stacked, no_sel=no_sel,
                           n_agree=sum(1 for f in rows if f["agree"]), max_legs=MAX_LEGS,
                           missing=len(missing), snippet=snippets.events_snippet(missing[:40]) if missing else None,
                                                      min_legs=min_legs, n_from_code=len(from_code), oldest=oldest, days=days,quick_days=_quick_days())


MAX_CODES = 10               # codes made in one go, at most (each trip fetches every game again first)
def _quick_days():
    """(label, start, end) for the day shortcuts on Fixtures across codes, in UTC (Ghana time)."""
    import datetime
    t = datetime.datetime.now(datetime.timezone.utc).date()
    d = lambda n: (t + datetime.timedelta(days=n)).isoformat()
    return [("Today", d(0), d(0)), ("Tomorrow", d(1), d(1)), ("Next 3 days", d(0), d(2)), ("This weekend", *(
        lambda sat: (sat.isoformat(), (sat + datetime.timedelta(days=1)).isoformat()))(
        t + datetime.timedelta(days=(5 - t.weekday()) % 7)))]

@bp.post("/codes/make")
def make():
    """Queue 'make a booking code' requests for the CodeMatch button, from ticked picks. More picks than one code
    takes (or than the 'picks per code' asked for) are split, in order, into several codes of near-equal size, all
    made in the same trip. Only makes the codes on SportyBet; staking stays with the user, on SportyBet."""
    import json as json_
    from flask import jsonify
    from .bridge import _save, make_job
    from . import num
    sels, seen = [], set()
    for raw in request.form.getlist("sel"):
        try:
            s_ = json_.loads(raw)
        except ValueError:
            continue
        if isinstance(s_, dict) and all(isinstance(s_.get(k), str) and s_.get(k) for k in ("eventId", "marketId", "outcomeId")) \
                and s_["eventId"].startswith("sr:match:"):
            s_ = {k: s_.get(k) for k in ("eventId", "marketId", "specifier", "outcomeId")}
            key = (s_["eventId"], s_["marketId"], s_.get("specifier") or "", s_["outcomeId"])
            if key not in seen:
                seen.add(key)
                sels.append(s_)
    if not sels:
        return jsonify(error="Tick at least one pick first."), 400
    per = int(min(max(num(request.form, "per_code", MAX_LEGS), 1), MAX_LEGS))
    parts = snippets.split_evenly(sels, per)
    if len(parts) > MAX_CODES:
        return jsonify(error=f"That would be {len(parts)} codes; at most {MAX_CODES} are made in one go "
                             f"({MAX_CODES * per} picks at {per} a code)."), 400
    # Fetch every game in the codes again first, so the odds are checked against SportyBet's current prices; the
    # app then shows what moved next to the new codes. The bookmark runs the requests in order, in one trip.
    con = get_db()
    eids = list(dict.fromkeys(s_["eventId"] for s_ in sels))
    names = store.game_names(con, eids)
    then = store.find_picks(con, sels)
    part_of = {id(s_): i for i, p in enumerate(parts, 1) for s_ in p}
    check = [{"sel": s_, "match": names.get(s_["eventId"], s_["eventId"]), "part": part_of[id(s_)],
              **({k: t[k] for k in ("label", "odds", "prob")} if t else {"label": None, "odds": None, "prob": None})}
             for s_, t in zip(sels, then)]
    make = [r for i, p in enumerate(parts, 1) for r in snippets.make_code_requests(p, (i, len(parts)))]
    reqs = snippets.events_snippet([(e, names.get(e, e)) for e in eids]).requests + make
    label = make[0]["label"] if len(parts) == 1 else f"make {len(parts)} booking codes ({len(sels)} picks)"
    job = make_job(con, label, reqs, check=check)
    job["n_make"] = len(parts)
    _save(con, job)
    return jsonify(id=job["id"], n=len(reqs), codes=len(parts))


@bp.post("/code/<code>/delete")
def delete(code):
    store.delete_code(get_db(), code.upper())
    return redirect(url_for("codes.index"))


@bp.post("/codes/delete")
def delete_many():
    """Delete the ticked codes, or every code when all=1."""
    con = get_db()
    which = request.form.get("all")
    if which == "1":
        targets = [c["code"] for c in store.codes(con)]
    elif which == "hub":
        targets = [c["code"] for c in store.codes(con) if c.get("source") == "hub"]
    else:
        targets = [c.upper() for c in request.form.getlist("code")]
    for c in targets:
        store.delete_code(con, c)
    msgs = [(True, f"Deleted {len(targets)} code{'s' if len(targets) != 1 else ''}.")] if targets else \
        [(False, "No codes ticked.")]
    return _index(msgs=msgs)


@bp.get("/match/<path:event_id>")
def old_match_link(event_id):
    return redirect(url_for("games.game", event_id=event_id))


@bp.get("/guide")
def guide():
    """Comprehensive user guide explaining setup, concepts, and quantitative advantage tools."""
    return render_template("guide.html")
