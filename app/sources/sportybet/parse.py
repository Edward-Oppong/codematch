"""Read SportyBet's JSON responses: booking codes, games, league lists, the league directory."""
from urllib.parse import quote


class ParseError(ValueError):
    pass


def classify(obj):
    """Which kind of response this is, or None if it isn't one the app uses."""
    if not isinstance(obj, dict) or "data" not in obj:
        return None
    d = obj["data"]
    if isinstance(d, dict):
        if "shareCode" in d:
            return "code"
        if "eventId" in d and "markets" in d:
            return "event"
        if "sportList" in d:
            return "directory"
    if isinstance(d, list) and d:
        if isinstance(d[0], dict) and "events" in d[0]:
            return "league"
        if isinstance(d[0], dict) and "shareCode" in d[0] and "shareCodeDetail" in d[0]:
            return "hub"
        if all(isinstance(x, str) and x.startswith("sr:match:") for x in d[:20]):
            return "banned"
    return None


def norm_market(desc, home, away):
    """'Arsenal Over/Under' -> 'Home Over/Under' so pick types compare across games."""
    for name, tag in ((home, "Home"), (away, "Away")):
        if desc.startswith(name + " "):
            return tag + desc[len(name):]
    return desc


def parse_code(body):
    """A booking-code response -> list of selection dicts. Never keeps the creator's userId."""
    if body.get("bizCode") != 10000 or not body.get("data"):
        raise ParseError(body.get("message") or "code not found or expired")
    data = body["data"]
    games = {o["eventId"]: o for o in data.get("outcomes", [])}
    out = []
    # every selection is a leg, including two legs on the same game
    for sel in data.get("ticket", {}).get("selections", []):
        o = games.get(sel["eventId"])
        if not o:
            continue
        spec_ = sel.get("specifier") or ""
        market = next((m for m in o.get("markets", []) if m["id"] == sel["marketId"]
                       and (m.get("specifier") or "") == spec_), None) or \
            next((m for m in o.get("markets", []) if m["id"] == sel["marketId"]), None)
        outcome = next((x for x in (market or {}).get("outcomes", [])
                        if x["id"] == sel["outcomeId"]), None)
        if not market or not outcome:
            continue
        tour = o["sport"]["category"]["tournament"]["name"]
        spec = sel.get("specifier", "")
        out.append({
            "sel_key": f'{sel["eventId"]}|{sel["marketId"]}|{spec}|{sel["outcomeId"]}',
            "event_id": sel["eventId"],
            "match": f'{o["homeTeamName"]} v {o["awayTeamName"]}',
            "league": f'{o["sport"]["category"]["name"]} {tour}',
            "market": market["desc"],
            "pick": outcome["desc"],
            "odds": float(outcome["odds"]),
            "start_ms": o.get("estimateStartTime"),
            "market_id": sel["marketId"], "specifier": spec, "outcome_id": sel["outcomeId"],
            "prob": float(outcome["probability"]) if outcome.get("probability") not in (None, "") else None,
            "pick_type": f'{norm_market(market["desc"], o["homeTeamName"], o["awayTeamName"])}: {outcome["desc"]}',
        })
    return out


def parse_hub(body, league_name=None):
    """A Code Hub list (POST /orders/bookingCode/filter) -> [{'code', 'popularity', 'sels'}]. Each code in the list
    already carries every pick with its odds and SportyBet's probability, so no second request per code is needed.
    The selections have the same shape and keys as parse_code's, so a code fetched either way is the same code.
    Never keeps the creator's userId. league_name(tournament_id) gives a readable league name when one is known.
    Only accumulators (orderType 2) are kept: in other order types the listed total isn't the product of the legs'
    odds (a 3-leg orderType 4 code listed at 4,258 had legs multiplying to 9 million), so they aren't one
    multiple and reviewing them as one would be wrong. Returns (codes, number left out)."""
    if body.get("bizCode") != 10000:
        raise ParseError(body.get("message") or "Code Hub list not available")
    league_name = league_name or (lambda tid: tid or "?")
    out, skipped = [], 0
    for c in body.get("data") or []:
        code = str(c.get("shareCode") or "").upper()
        if not code:
            continue
        if c.get("orderType", 2) != 2:
            skipped += 1
            continue
        sels = []
        for d in c.get("shareCodeDetail") or []:
            if d.get("sportId", "sr:sport:1") != "sr:sport:1":
                continue
            mid, oid, spec = str(d["marketId"]), str(d["outcomeId"]), d.get("marketSpecifiers") or ""
            home, away = d.get("homeTeamName", "?"), d.get("awayTeamName", "?")
            desc, pick = d.get("marketDescription", ""), d.get("outcomeDescription", "")
            prob = d.get("probability")
            sels.append({
                "sel_key": f'{d["eventId"]}|{mid}|{spec}|{oid}',
                "event_id": d["eventId"], "match": f"{home} v {away}",
                "league": league_name(d.get("tournamentId")),
                "market": desc, "pick": pick, "odds": float(d["odds"]), "start_ms": d.get("startTime"),
                "market_id": mid, "specifier": spec, "outcome_id": oid,
                "prob": float(prob) if prob not in (None, "") else None,
                "pick_type": f"{norm_market(desc, home, away)}: {pick}",
            })
        if sels:
            out.append({"code": code, "popularity": c.get("popularity"), "sels": sels})
    return out, skipped


def event_info(ev, league=None):
    """The fields the app indexes a game by. League responses don't always repeat the league on each game,
    so the enclosing league ({'id','name','category'}) fills the gaps."""
    cat = (ev.get("sport") or {}).get("category") or {}
    tour = cat.get("tournament") or {}
    league = league or {}
    return {"event_id": ev["eventId"],
            "tournament_id": tour.get("id") or league.get("id"),
            "tournament": tour.get("name") or league.get("name"),
            "category": cat.get("name") or league.get("category"),
            "home": ev.get("homeTeamName", "?"), "away": ev.get("awayTeamName", "?"),
            "start_ms": ev.get("estimateStartTime")}


def final_score(ev):
    """(h1, a1, h2, a2) for a finished game, from its per-half scores, or None. Football markets settle on
    the first 90 minutes, so only the first two periods count."""
    if ev.get("matchStatus") != "Ended":
        return None
    halves = ev.get("gameScore") or []
    try:
        (h1, a1), (h2, a2) = [tuple(int(x) for x in s.split(":")) for s in halves[:2]]
    except (ValueError, TypeError):
        return None
    return h1, a1, h2, a2


def parse_directory(body):
    """League directory -> (top leagues, all categories with their leagues)."""
    data = body["data"]
    cats = data["sportList"][0]["categories"]
    top = []
    for sport in data.get("popularEvents", []):
        for c in sport.get("categories", []):
            if c.get("id") == "sr:category:top":
                top = c["tournaments"]
    if not top:   # older directory responses: leagues SportyBet tags with their country are the featured ones
        top = [t for c in cats for t in c.get("tournaments", []) if t.get("categoryName")]
    return top, cats


def match_url(ev, info=None):
    """Public match page: /gh/sport/football/<Country>/<League>/<Home>_vs_<Away>/<eventId>."""
    info = info or event_info(ev)
    seg = lambda s: quote((s or "").strip().replace(" ", "_"), safe="_-.()'")
    sport = ((ev.get("sport") or {}).get("name") or "Football").lower()
    return "https://www.sportybet.com/gh/sport/%s/%s/%s/%s_vs_%s/%s" % (
        sport, seg(info["category"]), seg(info["tournament"]), seg(info["home"]), seg(info["away"]), info["event_id"])
