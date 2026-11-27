"""Everything the app saves: games, booking codes, price history, and a few stored responses."""
from collections import defaultdict
import json
import time

from .analysis import markets
from .sources.sportybet.parse import event_info


# ---------- stored responses (league lists, directory, blocked games) ----------
def put_blob(con, key, kind, obj, n=0, name=""):
    con.execute("INSERT OR REPLACE INTO blobs VALUES(?,?,?,?,?,?)",
                (key, kind, int(time.time()), n, name, json.dumps(obj)))
    con.commit()


def get_blob(con, key):
    r = con.execute("SELECT body, saved_at, n FROM blobs WHERE key=?", (key,)).fetchone()
    return (json.loads(r["body"]), r["saved_at"], r["n"]) if r else None


def banned_ids(con):
    r = get_blob(con, "banned")
    return set(r[0]) if r else set()


def directory(con):
    r = get_blob(con, "directory")
    return (r[0], r[1]) if r else (None, None)


def new_leagues(con):
    """Tournament ids that appeared in the league list at its last refresh."""
    r = get_blob(con, "directory_new")
    return set(r[0]) if r else set()


# ---------- games ----------
def save_event(con, ev, league=None, saved_at=None, history=True, commit=True):
    """Save one game. A game imported with all its markets is not replaced by a later copy with fewer
    (a league import), but the newer prices still go into the history."""
    info = event_info(ev, league)
    n = len(ev.get("markets") or [])
    ts = saved_at or int(time.time())
    priced = {fam: markets.build_priced(ev, fam) for fam in markets.FAMILIES} if n else {}
    if history and n:
        record_history(con, ev, ts, priced)
    old = con.execute("SELECT n_markets, tournament_id FROM events WHERE event_id=?", (info["event_id"],)).fetchone()
    name = f'{info["home"]} v {info["away"]}'
    if old and old["n_markets"] > n:
        if not old["tournament_id"] and info["tournament_id"]:
            con.execute("UPDATE events SET tournament_id=?, tournament=?, category=? WHERE event_id=?",
                        (info["tournament_id"], info["tournament"], info["category"], info["event_id"]))
        msg = (f"{name}: kept the fuller copy already imported ({old['n_markets']} markets, this one had {n}); "
               "its prices were still recorded")
    else:
        con.execute("INSERT OR REPLACE INTO events VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (info["event_id"], info["tournament_id"], info["tournament"], info["category"], info["home"],
                     info["away"], info["start_ms"], n, ts, json.dumps(ev)))
        save_picks(con, ev, priced, ts)
        msg = f"{name}: saved {n} markets"
    if commit:
        con.commit()
    return msg


def get_event(con, event_id):
    """(game dict, saved_at, number of markets) or None."""
    r = con.execute("SELECT body, saved_at, n_markets FROM events WHERE event_id=?", (event_id,)).fetchone()
    return (json.loads(r["body"]), r["saved_at"], r["n_markets"]) if r else None


def list_events(con, start_ms=None, end_ms=None, tournament_ids=None, q=None, with_body=False):
    cols = "*" if with_body else "event_id, tournament_id, tournament, category, home, away, start_ms, n_markets, saved_at"
    sql, args = f"SELECT {cols} FROM events WHERE 1=1", []
    if start_ms is not None:
        sql += " AND start_ms >= ?"
        args.append(start_ms)
    if end_ms is not None:
        sql += " AND start_ms < ?"
        args.append(end_ms)
    if tournament_ids:
        sql += f" AND tournament_id IN ({','.join('?' * len(tournament_ids))})"
        args += list(tournament_ids)
    if q:
        sql += " AND (home LIKE ? OR away LIKE ? OR tournament LIKE ?)"
        args += [f"%{q}%"] * 3
    rows = [dict(r) for r in con.execute(sql + " ORDER BY start_ms, home", args)]
    if with_body:
        for r in rows:
            r["ev"] = json.loads(r.pop("body"))
    return rows


# ---------- each game's picks, priced once at import ----------
# Leagues and target odds only need each pick's odds, chance and SportyBet ids. Reading those from rows is much faster
# than loading the whole saved game (often over 1 MB) and working out every market again on each page view.
PICK_COLS = ("family", "label", "odds", "prob", "ret", "push", "cond", "push_prob", "refund_on", "mid", "spec", "oid",
             "odesc", "bkey", "cat", "side", "bname", "prob_ok", "mkt_kept")


def save_picks(con, ev, priced_by_family, saved_at):
    """Save one game's priced picks, each with its bet type (for the screener), whether SportyBet's probability
    for it can be relied on, and its whole market's margin when that can be worked out."""
    from .analysis import bettypes
    event_id = ev["eventId"]
    home, away = ev.get("homeTeamName") or "", ev.get("awayTeamName") or ""
    checks = bettypes.market_checks(ev)
    rows = []
    for fam, priced in priced_by_family.items():
        for label, v in priced.items():
            cat, key, side, name = bettypes.classify(label, home, away)
            reliable, kept = checks.get((v["mid"], v["spec"]), (False, None))
            reliable = reliable and not v.get("cond") and v.get("prob") is not None and 0 < v["prob"] < 1
            rows.append((event_id, fam, label, v["odds"], v["prob"], v["ret"], 1 if v.get("push") else 0,
                         1 if v.get("cond") else 0, v.get("push_prob"), v.get("refund_on"), v["mid"], v["spec"],
                         v.get("oid"), v.get("desc"), key, cat, side, name, 1 if reliable else 0, kept))
    con.execute("DELETE FROM picks WHERE event_id=?", (event_id,))
    con.executemany(f"INSERT INTO picks(event_id, {', '.join(PICK_COLS)}) VALUES(?,{','.join('?' * len(PICK_COLS))})",
                    rows)
    con.execute("INSERT OR REPLACE INTO priced_at VALUES(?,?,?)", (event_id, saved_at, 1 if ev.get("banned") else 0))


def ensure_picks(con, event_ids):
    """Price any of these games not priced since they were last saved (games saved by an older version of the
    app, the first time they're viewed). Returns the ids SportyBet marked as blocked."""
    if not event_ids:
        return set()
    done, banned = {}, set()
    for chunk in _chunks(list(event_ids)):
        q = f"""SELECT e.event_id, e.saved_at, p.saved_at AS priced, p.banned FROM events e
                LEFT JOIN priced_at p ON p.event_id = e.event_id WHERE e.event_id IN ({','.join('?' * len(chunk))})"""
        for r in con.execute(q, chunk):
            done[r["event_id"]] = r["priced"] == r["saved_at"]
            if r["banned"]:
                banned.add(r["event_id"])
    todo = [e for e, ok in done.items() if not ok]
    for eid in todo:
        row = get_event(con, eid)
        if not row:
            continue
        ev, saved_at, _ = row
        save_picks(con, ev, {f: markets.build_priced(ev, f) for f in markets.FAMILIES}, saved_at)
        if ev.get("banned"):
            banned.add(eid)
    if todo:
        con.commit()
    return banned


def load_picks(con, event_ids, families, minp=0.0, maxp=1.0, mino=1.0, maxo=1000.0):
    """{event id: {label: pick}} for these games, only picks in these families and inside the chance and odds
    window. Each pick has the same keys build_priced gives, apart from the win / refund masks."""
    out = {e: {} for e in event_ids}
    fams = list(families)
    for chunk in _chunks(list(event_ids), 900 - len(fams)):
        q = f"""SELECT event_id, {', '.join(PICK_COLS)} FROM picks
                WHERE event_id IN ({','.join('?' * len(chunk))}) AND family IN ({','.join('?' * len(fams))})
                  AND prob >= ? AND prob <= ? AND odds >= ? AND odds < ?"""
        for r in con.execute(q, [*chunk, *fams, minp - 1e-12, maxp + 1e-12, mino, maxo]):
            v = dict(r)
            out[v.pop("event_id")][v["label"]] = v
    return out


def find_picks(con, sels):
    """For SportyBet selections [{eventId, marketId, specifier, outcomeId}], each one's saved pick (label, odds,
    chance) and when its game was priced, or None when the game isn't saved or the pick isn't on offer in it."""
    out = []
    for s_ in sels:
        r = con.execute("""SELECT p.label, p.odds, p.prob, p.ret, p.push, p.family, a.saved_at FROM picks p
                           JOIN priced_at a ON a.event_id = p.event_id
                           WHERE p.event_id=? AND p.mid=? AND p.spec=? AND p.oid=?""",
                        (s_["eventId"], s_["marketId"], s_.get("specifier") or "", s_["outcomeId"])).fetchone()
        out.append(dict(r) if r else None)
    return out


def _id_table(con, event_ids, name="sel_ids"):
    """Put these game ids in a temporary table to join on (no limit on how many)."""
    con.execute(f"CREATE TEMP TABLE IF NOT EXISTS {name}(event_id TEXT PRIMARY KEY)")
    con.execute(f"DELETE FROM {name}")
    con.executemany(f"INSERT OR IGNORE INTO {name} VALUES(?)", [(i,) for i in event_ids])


def bet_types(con, event_ids):
    """Every bet type in these games, for the screener: [{cat, bkey, bname, games, reliable}], where games is how
    many games offer it and reliable how many of its picks have a probability that can be relied on."""
    if not event_ids:
        return []
    _id_table(con, event_ids)
    return [dict(r) for r in con.execute("""
        SELECT p.cat, p.bkey, MAX(p.bname) AS bname, COUNT(DISTINCT p.event_id) AS games, SUM(p.prob_ok) AS reliable
        FROM picks p JOIN sel_ids s ON s.event_id = p.event_id GROUP BY p.bkey""")]


def screen_picks(con, event_ids, keys, mino=1.0, maxo=1000.0):
    """The picks of these bet types in these games, inside the odds window, with each game's teams and kick-off."""
    if not event_ids or not keys:
        return []
    _id_table(con, event_ids)
    q = f"""SELECT p.*, e.home, e.away, e.start_ms, e.tournament, e.category, e.saved_at, e.n_markets
            FROM picks p JOIN sel_ids s ON s.event_id = p.event_id JOIN events e ON e.event_id = p.event_id
            WHERE p.bkey IN ({','.join('?' * len(keys))}) AND p.odds >= ? AND p.odds <= ?"""
    return [dict(r) for r in con.execute(q, [*keys, mino, maxo])]


def value_singles(con, event_ids, mino=1.10, maxo=10.0, minp=0.40, min_ret=0.92, family=None,
                  order_by="prob", direction="all", one_per_game=False, limit=100):
    """Singles with the highest expected return (smallest bookmaker margin), reliable chances,
    and kick-off times for advantage value betting across all market families."""
    if not event_ids:
        return []
    _id_table(con, event_ids)
    extra_clause = ""
    extra_args = []
    if family:
        fam = family.lower()
        if fam == "corners":
            extra_clause = " AND p.family = 'corners'"
        elif fam == "bookings":
            extra_clause = " AND p.family = 'bookings'"
        elif fam == "handicap":
            extra_clause = " AND (p.label LIKE '%Handicap%' OR p.label LIKE '%Asian%')"
        elif fam in ("halves", "half"):
            extra_clause = " AND (p.label LIKE '%Half%' OR p.label LIKE '%HT%')"
        elif fam in ("btts", "gg"):
            extra_clause = " AND (p.label LIKE '%Both Teams%' OR p.label LIKE '%GG%')"
        elif fam in ("dc", "double"):
            extra_clause = " AND (p.label LIKE '%Double Chance%' OR p.label LIKE '%No Bet%' OR p.label LIKE '%1UP%' OR p.label LIKE '%2UP%')"
        elif fam == "stats":
            extra_clause = " AND p.family IN ('fouls', 'offsides', 'shots', 'shots on target', 'throw-ins', 'tackles')"
        elif fam in ("player", "players", "scorer"):
            extra_clause = " AND (p.label LIKE '%Player%' OR p.label LIKE '%Scorer%' OR p.label LIKE '%Goalscorer%')"
        elif fam in ("keeper", "goalkeeper", "saves"):
            extra_clause = " AND (p.label LIKE '%Save%' OR p.label LIKE '%Goalkeeper%' OR p.label LIKE '%Keeper%')"
        elif fam == "goals":
            extra_clause = " AND p.family = 'goals' AND p.label NOT LIKE '%Handicap%'"
        else:
            extra_clause = " AND p.family = ?"
            extra_args.append(fam)

    if direction == "over":
        extra_clause += " AND p.label LIKE '%Over%'"
    elif direction == "under":
        extra_clause += " AND p.label LIKE '%Under%'"
    elif direction == "no_extreme_under":
        extra_clause += " AND NOT (p.label LIKE '%Under 4%' OR p.label LIKE '%Under 5%' OR p.label LIKE '%Under 6%')"
    elif direction == "no_unders":
        extra_clause += " AND p.label NOT LIKE '%Under%'"

    order_map = {
        "prob": "p.prob DESC, p.ret DESC",
        "return": "p.ret DESC, p.prob DESC",
        "odds": "p.odds DESC, p.prob DESC",
        "kickoff": "e.start_ms ASC, p.prob DESC"
    }
    order_clause = order_map.get(order_by, "p.prob DESC, p.ret DESC")

    fetch_limit = limit * 4 if one_per_game else limit
    q = f"""SELECT p.*, e.home, e.away, e.start_ms, e.tournament, e.category, e.saved_at, e.n_markets
           FROM picks p JOIN sel_ids s ON s.event_id = p.event_id JOIN events e ON e.event_id = p.event_id
           WHERE p.prob_ok = 1 AND p.cond = 0 AND p.ret IS NOT NULL AND p.ret >= ?
             AND p.prob >= ? AND p.odds >= ? AND p.odds <= ?{extra_clause}
           ORDER BY {order_clause} LIMIT ?"""
    rows = [dict(r) for r in con.execute(q, [min_ret, minp, mino, maxo, *extra_args, fetch_limit])]
    if one_per_game:
        seen = set()
        unique = []
        for r in rows:
            if r["event_id"] not in seen:
                seen.add(r["event_id"])
                unique.append(r)
                if len(unique) >= limit:
                    break
        return unique
    return rows


def steam_movers(con, event_ids, min_pct=2.0, direction="all", limit=100):
    """Find picks in the given games where the current odds differ from the earliest recorded odds in history.
    direction: 'steam' (odds shortened / dropped), 'drift' (odds lengthened / rose), or 'all'."""
    if not event_ids:
        return []
    _id_table(con, event_ids)
    q = """
    SELECT p.*, e.home, e.away, e.start_ms, e.tournament, e.category,
           f.first_odds, f.first_prob, f.first_ts,
           ((p.odds - f.first_odds) / f.first_odds) * 100.0 AS move_pct
    FROM picks p
    JOIN sel_ids s ON s.event_id = p.event_id
    JOIN events e ON e.event_id = p.event_id
    JOIN (
        SELECT h.event_id, h.label, h.odds AS first_odds, h.prob AS first_prob, h.ts AS first_ts
        FROM history h
        JOIN (
            SELECT event_id, label, MIN(ts) AS min_ts
            FROM history
            GROUP BY event_id, label
        ) m ON h.event_id = m.event_id AND h.label = m.label AND h.ts = m.min_ts
    ) f ON f.event_id = p.event_id AND f.label = p.label
    WHERE p.prob_ok = 1 AND p.cond = 0 AND ABS((p.odds - f.first_odds) / f.first_odds) * 100.0 >= ?
    """
    args = [min_pct]
    if direction == "steam":
        q += " AND p.odds < f.first_odds"
    elif direction == "drift":
        q += " AND p.odds > f.first_odds"
    q += " ORDER BY ABS(move_pct) DESC LIMIT ?"
    args.append(limit)
    return [dict(r) for r in con.execute(q, args)]


def margins(con, event_ids, by="market"):
    """How much SportyBet keeps (1 minus the return) on average, over the saved picks of these games, grouped by
    market (family and market name) or by league and family, split by odds zone. Picks whose return couldn't be
    worked out (refund picks without a priced refund result) are left out."""
    from .analysis.picks import ZONES
    if not event_ids:
        return []
    zone_cols = ", ".join(
        f"AVG(CASE WHEN p.odds >= {lo} AND p.odds < {hi} THEN 1 - p.ret END) AS z_{k}, "
        f"SUM(p.odds >= {lo} AND p.odds < {hi}) AS n_{k}" for k, _, lo, hi in ZONES)
    group = ("p.family, substr(p.label, 1, instr(p.label, ': ') - 1)" if by == "market"
             else "e.tournament_id, p.family")
    name = ("substr(p.label, 1, instr(p.label, ': ') - 1) AS market" if by == "market"
            else "MAX(e.category) AS category, MAX(e.tournament) AS tournament, e.tournament_id")
    ids = list(event_ids)
    con.execute("CREATE TEMP TABLE IF NOT EXISTS margin_ids(event_id TEXT PRIMARY KEY)")
    con.execute("DELETE FROM margin_ids")
    con.executemany("INSERT OR IGNORE INTO margin_ids VALUES(?)", [(i,) for i in ids])
    q = f"""SELECT p.family, {name}, COUNT(*) AS n, COUNT(DISTINCT p.event_id) AS games, AVG(1 - p.ret) AS kept,
                   {zone_cols}
            FROM picks p JOIN margin_ids m ON m.event_id = p.event_id JOIN events e ON e.event_id = p.event_id
            WHERE p.cond = 0 GROUP BY {group} ORDER BY kept"""
    rows = [dict(r) for r in con.execute(q)]
    con.execute("DELETE FROM margin_ids")
    return rows


def families_of(con, event_ids):
    """{event id: set of families it has saved picks in}."""
    out = {}
    for chunk in _chunks(list(event_ids)):
        for r in con.execute(f"SELECT DISTINCT event_id, family FROM picks WHERE event_id IN ({','.join('?' * len(chunk))})",
                             chunk):
            out.setdefault(r["event_id"], set()).add(r["family"])
    return out


def game_names(con, event_ids):
    return {r["event_id"]: f'{r["home"]} v {r["away"]}' for r in con.execute(
        f"SELECT event_id, home, away FROM events WHERE event_id IN ({','.join('?' * len(event_ids))})",
        list(event_ids))} if event_ids else {}


def _chunks(xs, n=900):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def _forget_picks(con, ids):
    con.executemany("DELETE FROM picks WHERE event_id=?", [(i,) for i in ids])
    con.executemany("DELETE FROM priced_at WHERE event_id=?", [(i,) for i in ids])


def imported_leagues(con):
    return [dict(r) for r in con.execute("""
        SELECT tournament_id, MAX(tournament) AS tournament, MAX(category) AS category, COUNT(*) AS n,
               MIN(start_ms) AS first, MAX(start_ms) AS last, MAX(saved_at) AS saved_at,
               SUM(n_markets >= 100) AS n_full
        FROM events WHERE tournament_id IS NOT NULL GROUP BY tournament_id ORDER BY category, tournament""")]


def delete_events(con, before_ms=None):
    """Delete games (and their price history) that kicked off before before_ms, or every game when None."""
    where, args = ("WHERE start_ms < ?", (before_ms,)) if before_ms is not None else ("", ())
    ids = [r["event_id"] for r in con.execute(f"SELECT event_id FROM events {where}", args)]
    con.executemany("DELETE FROM history WHERE event_id=?", [(i,) for i in ids])
    _forget_picks(con, ids)
    con.execute(f"DELETE FROM events {where}", args)
    if before_ms is None:
        con.execute("DELETE FROM blobs WHERE kind='league'")
    con.commit()
    return len(ids)


def delete_event(con, event_id):
    """One game, with its price history and final score. Codes that contain it keep their legs."""
    con.execute("DELETE FROM history WHERE event_id=?", (event_id,))
    con.execute("DELETE FROM results WHERE event_id=?", (event_id,))
    _forget_picks(con, [event_id])
    n = con.execute("DELETE FROM events WHERE event_id=?", (event_id,)).rowcount
    con.commit()
    return n


def delete_league(con, tournament_id):
    """A league's games (with their history and scores) and the league itself."""
    ids = [r["event_id"] for r in con.execute("SELECT event_id FROM events WHERE tournament_id=?", (tournament_id,))]
    for t in ("history", "results"):
        con.executemany(f"DELETE FROM {t} WHERE event_id=?", [(i,) for i in ids])
    _forget_picks(con, ids)
    con.execute("DELETE FROM events WHERE tournament_id=?", (tournament_id,))
    con.execute("DELETE FROM blobs WHERE key=?", (f"league:{tournament_id}",))
    con.commit()
    return len(ids)


def delete_bet_record(con):
    """Every recorded bet, every hand-marked leg result and the Code Hub track record. Codes, games and settings
    stay."""
    n = con.execute("SELECT COUNT(*) FROM bets").fetchone()[0]
    con.execute("DELETE FROM bets")
    con.execute("DELETE FROM leg_results")
    con.execute("DELETE FROM hub_outcomes")
    con.commit()
    return n


def delete_everything(con):
    """Codes, games, leagues, price history. The league directory is kept, since it rarely changes."""
    n_games = delete_events(con)
    n_codes = con.execute("SELECT COUNT(*) FROM codes").fetchone()[0]
    con.execute("DELETE FROM selections")
    con.execute("DELETE FROM codes")
    con.execute("DELETE FROM leg_results")
    con.execute("DELETE FROM results")
    con.execute("DELETE FROM blobs WHERE kind NOT IN ('directory', 'meta')")   # the bet record and settings stay
    con.commit()
    return n_codes, n_games


def counts(con):
    q = lambda sql: con.execute(sql).fetchone()[0]
    return {"codes": q("SELECT COUNT(*) FROM codes"), "games": q("SELECT COUNT(*) FROM events"),
            "old_games": q(f"SELECT COUNT(*) FROM events WHERE start_ms < {int(time.time() * 1000) - 86400000}")}


# ---------- results, bets, settings ----------
def save_result(con, event_id, h1, a1, h2, a2):
    con.execute("INSERT OR REPLACE INTO results VALUES(?,?,?,?,?,?)", (event_id, h1, a1, h2, a2, int(time.time())))
    con.commit()


def results(con):
    return {r["event_id"]: (r["h1"], r["a1"], r["h2"], r["a2"]) for r in con.execute("SELECT * FROM results")}


def set_leg_result(con, code, sel_key, status):
    """Manual result for one leg ('won', 'lost', 'void'), or clear it with status None."""
    if status in ("won", "lost", "void"):
        con.execute("INSERT OR REPLACE INTO leg_results VALUES(?,?,?)", (code, sel_key, status))
    else:
        con.execute("DELETE FROM leg_results WHERE code=? AND sel_key=?", (code, sel_key))
    con.commit()


def manual_results(con):
    return {(r["code"], r["sel_key"]): r["status"] for r in con.execute("SELECT * FROM leg_results")}


def add_bet(con, code, stake, placed_at=None, payout=None):
    con.execute("INSERT INTO bets(code, stake, placed_at, payout) VALUES(?,?,?,?)",
                (code, stake, placed_at or int(time.time()), payout))
    con.commit()


def set_payout(con, bet_id, payout):
    """What SportyBet actually paid (for cash-outs or when a leg was settled differently). None = work it out."""
    con.execute("UPDATE bets SET payout=? WHERE id=?", (payout, bet_id))
    con.commit()


def delete_bet(con, bet_id):
    con.execute("DELETE FROM bets WHERE id=?", (bet_id,))
    con.commit()


def bets(con):
    return [dict(r) for r in con.execute("SELECT * FROM bets ORDER BY placed_at DESC, id DESC")]


def settings(con):
    r = get_blob(con, "settings")
    return r[0] if r else {}


def save_settings(con, **values):
    s = settings(con)
    s.update(values)
    put_blob(con, "settings", "meta", s)


# ---------- price history ----------
def record_history(con, ev, ts=None, priced=None):
    """Keep each price the first time it's seen and whenever it changes, so odds movement can be followed
    without storing every unchanged price at every import. priced: {family: build_priced(ev, family)}, if done."""
    ts = ts or int(time.time())
    priced = priced or {fam: markets.build_priced(ev, fam) for fam in markets.FAMILIES}
    last = {r["label"]: r["odds"] for r in con.execute(
        """SELECT h.label, h.odds FROM history h
           JOIN (SELECT label, MAX(ts) AS ts FROM history WHERE event_id=? GROUP BY label) m
             ON h.label=m.label AND h.ts=m.ts WHERE h.event_id=?""", (ev["eventId"], ev["eventId"]))}
    rows = [(ev["eventId"], fam, label, v["odds"], v["prob"], ts)
            for fam in markets.FAMILIES for label, v in priced.get(fam, {}).items()
            if last.get(label) != v["odds"]]
    con.executemany("INSERT INTO history VALUES(?,?,?,?,?,?)", rows)
    return len(rows)


def price_history(con, event_id, label):
    return [dict(r) for r in con.execute(
        "SELECT ts, odds, prob FROM history WHERE event_id=? AND label=? ORDER BY ts", (event_id, label))]


def prune_history(con):
    """Remove rows that repeat the previous price for the same pick (left by older versions of the app)."""
    before = con.execute("SELECT COUNT(*) FROM history").fetchone()[0]
    con.execute("""DELETE FROM history WHERE rowid IN (
        SELECT rowid FROM (SELECT rowid, odds, LAG(odds) OVER (PARTITION BY event_id, label ORDER BY ts) AS prev
                           FROM history) WHERE prev = odds)""")
    con.commit()
    return before - con.execute("SELECT COUNT(*) FROM history").fetchone()[0]


def first_prices(con, event_id):
    """{label: odds at the first import} for one game."""
    q = """SELECT h.label, h.odds FROM history h
           WHERE h.event_id=? AND h.ts=(SELECT MIN(ts) FROM history WHERE event_id=h.event_id AND label=h.label)"""
    return {r["label"]: r["odds"] for r in con.execute(q, (event_id,))}


# ---------- booking codes ----------
def save_code(con, code, sels, source=None, popularity=None, commit=True):
    """Save a code's legs, replacing an older copy. source: 'hub' for a code from SportyBet's Code Hub; a later fetch
    of the same code by hand keeps that label and its popularity."""
    con.execute("""INSERT INTO codes(code, fetched_at, n_selections, source, popularity) VALUES(?,?,?,?,?)
                   ON CONFLICT(code) DO UPDATE SET fetched_at=excluded.fetched_at, n_selections=excluded.n_selections,
                   source=COALESCE(excluded.source, codes.source),
                   popularity=COALESCE(excluded.popularity, codes.popularity)""",
                (code, int(time.time()), len(sels), source, popularity))
    con.execute("DELETE FROM selections WHERE code=?", (code,))
    con.executemany(
        """INSERT OR IGNORE INTO selections(code, sel_key, event_id, match, league, market, pick, odds, start_ms,
               market_id, specifier, outcome_id, prob, pick_type) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [(code, s["sel_key"], s["event_id"], s["match"], s["league"], s["market"],
          s["pick"], s["odds"], s["start_ms"], s.get("market_id"), s.get("specifier"), s.get("outcome_id"),
          s.get("prob"), s.get("pick_type")) for s in sels])
    if commit:
        con.commit()


def delete_code(con, code):
    con.execute("DELETE FROM selections WHERE code=?", (code,))
    con.execute("DELETE FROM codes WHERE code=?", (code,))
    con.commit()


def codes(con):
    return [dict(r) for r in con.execute(
        "SELECT code, fetched_at, n_selections, source, popularity FROM codes ORDER BY fetched_at DESC")]


# Names for the leagues Code Hub codes use most, so they read well before the league list is fetched. The league
# directory and imported games take precedence.
KNOWN_LEAGUES = {
    "sr:tournament:17": "England Premier League", "sr:tournament:18": "England Championship",
    "sr:tournament:24": "England League One", "sr:tournament:25": "England League Two",
    "sr:tournament:19": "England FA Cup", "sr:tournament:21": "England EFL Cup",
    "sr:tournament:8": "Spain LaLiga", "sr:tournament:54": "Spain LaLiga 2",
    "sr:tournament:23": "Italy Serie A", "sr:tournament:53": "Italy Serie B",
    "sr:tournament:35": "Germany Bundesliga", "sr:tournament:44": "Germany 2. Bundesliga",
    "sr:tournament:217": "Germany DFB Pokal", "sr:tournament:34": "France Ligue 1", "sr:tournament:182": "France Ligue 2",
    "sr:tournament:37": "Netherlands Eredivisie", "sr:tournament:238": "Portugal Liga Portugal",
    "sr:tournament:36": "Scotland Premiership", "sr:tournament:38": "Belgium Pro League",
    "sr:tournament:52": "Turkey Super Lig", "sr:tournament:203": "Russia Premier League",
    "sr:tournament:185": "Greece Super League", "sr:tournament:39": "Denmark Superliga",
    "sr:tournament:40": "Sweden Allsvenskan", "sr:tournament:20": "Norway Eliteserien",
    "sr:tournament:215": "Switzerland Super League", "sr:tournament:45": "Austria Bundesliga",
    "sr:tournament:242": "USA MLS", "sr:tournament:325": "Brazil Serie A",
    "sr:tournament:7": "UEFA Champions League", "sr:tournament:679": "UEFA Europa League",
    "sr:tournament:34480": "UEFA Conference League",
}


def save_hub_outcome(con, code, popularity, prob, ret, status, multiplier, n_legs):
    """A finished Code Hub code's result, kept for the track record after the code itself is deleted."""
    con.execute("INSERT OR REPLACE INTO hub_outcomes VALUES(?,?,?,?,?,?,?,?)",
                (code, popularity, prob, ret, status, multiplier, n_legs, int(time.time())))


def hub_outcomes(con):
    return [dict(r) for r in con.execute("SELECT * FROM hub_outcomes")]


def purge_old_hub(con, before_ms):
    """Delete Code Hub codes whose last game kicked off before before_ms, unless a bet was recorded on them."""
    old = [r["code"] for r in con.execute(
        """SELECT c.code FROM codes c JOIN selections s ON s.code = c.code WHERE c.source = 'hub'
           AND c.code NOT IN (SELECT code FROM bets) GROUP BY c.code HAVING MAX(s.start_ms) < ?""", (before_ms,))]
    for c in old:
        con.execute("DELETE FROM selections WHERE code=?", (c,))
        con.execute("DELETE FROM leg_results WHERE code=?", (c,))
        con.execute("DELETE FROM codes WHERE code=?", (c,))
    if old:
        con.commit()
    return len(old)


def league_names(con):
    """tournament id -> 'Country League', from imported games and the league directory, for codes that arrive with
    only a tournament id (Code Hub)."""
    out = dict(KNOWN_LEAGUES)
    d, _ = directory(con)
    if d:
        try:
            for c in d["data"]["sportList"][0]["categories"]:
                for t in c.get("tournaments", []):
                    out[t["id"]] = f'{c.get("name", "")} {t.get("name", "")}'.strip()
        except (KeyError, IndexError, TypeError):
            pass
    for r in con.execute("SELECT DISTINCT tournament_id, tournament, category FROM events WHERE tournament_id IS NOT NULL"):
        out[r["tournament_id"]] = f'{r["category"] or ""} {r["tournament"] or ""}'.strip()
    return out


def load_legs(con, code):
    return [dict(r) for r in con.execute("SELECT * FROM selections WHERE code=? ORDER BY start_ms, match", (code,))]


def load_all_legs(con):
    """Load selections for all codes in a single query, grouped by code."""
    out = defaultdict(list)
    for r in con.execute("SELECT * FROM selections ORDER BY code, start_ms, match"):
        out[r["code"]].append(dict(r))
    return out


def top_selections(con, limit=25):
    return con.execute("""
        SELECT match, league, market, pick, COUNT(DISTINCT code) AS n, ROUND(AVG(odds),2) AS odds
        FROM selections GROUP BY sel_key HAVING n > 1 ORDER BY n DESC, match LIMIT ?""", (limit,)).fetchall()


def name_leagues(con):
    """Legs saved with only a tournament id (Code Hub, before the league was known) get its name once the league
    list or one of its games has been imported."""
    raw = [r["league"] for r in con.execute("SELECT DISTINCT league FROM selections WHERE league LIKE 'sr:tournament:%'")]
    if not raw:
        return 0
    names = league_names(con)
    n = 0
    for tid in raw:
        if names.get(tid):
            n += con.execute("UPDATE selections SET league=? WHERE league=?", (names[tid], tid)).rowcount
    con.commit()
    return n


# ---------- rollover tracker ----------

def create_rollover(con, name, start_stake, target_odds, target_amount):
    ts = int(time.time())
    cur = con.execute(
        "INSERT INTO rollovers(name,start_stake,target_odds,target_amount,current_step,current_stake,status,created_at,updated_at) VALUES(?,?,?,?,0,?,?,?,?)",
        (name, start_stake, target_odds, target_amount, start_stake, "active", ts, ts))
    con.commit()
    return cur.lastrowid


def get_rollover(con, rollover_id):
    r = con.execute("SELECT * FROM rollovers WHERE id=?", (rollover_id,)).fetchone()
    return dict(r) if r else None


def list_rollovers(con):
    return [dict(r) for r in con.execute("SELECT * FROM rollovers ORDER BY updated_at DESC")]


def rollover_steps(con, rollover_id):
    return [dict(r) for r in con.execute(
        "SELECT * FROM rollover_steps WHERE rollover_id=? ORDER BY step", (rollover_id,))]


def record_rollover_step(con, rollover_id, odds, result, note=""):
    """Record a won/lost step and update the rollover state accordingly."""
    rv = get_rollover(con, rollover_id)
    if not rv or rv["status"] != "active":
        return None
    step = rv["current_step"] + 1
    stake = rv["current_stake"]
    payout = round(stake * odds, 2) if result == "won" else 0.0
    ts = int(time.time())
    con.execute(
        "INSERT INTO rollover_steps(rollover_id,step,stake,odds,result,payout,note,played_at) VALUES(?,?,?,?,?,?,?,?)",
        (rollover_id, step, stake, odds, result, payout, note, ts))
    if result == "won":
        new_stake = payout
        new_status = "won" if rv["target_amount"] and payout >= rv["target_amount"] else "active"
    else:
        new_stake = rv["start_stake"]  # restart from initial stake on bust
        new_status = "bust"
    con.execute(
        "UPDATE rollovers SET current_step=?,current_stake=?,status=?,updated_at=? WHERE id=?",
        (step, new_stake, new_status, ts, rollover_id))
    con.commit()
    return {"step": step, "stake": stake, "odds": odds, "result": result, "payout": payout}


def restart_rollover(con, rollover_id):
    """Reset a bust rollover back to active from the starting stake."""
    rv = get_rollover(con, rollover_id)
    if not rv:
        return
    ts = int(time.time())
    con.execute(
        "UPDATE rollovers SET current_step=0,current_stake=start_stake,status='active',updated_at=? WHERE id=?",
        (ts, rollover_id))
    con.commit()


def delete_rollover(con, rollover_id):
    con.execute("DELETE FROM rollover_steps WHERE rollover_id=?", (rollover_id,))
    con.execute("DELETE FROM rollovers WHERE id=?", (rollover_id,))
    con.commit()


def rollover_ladder(start_stake, target_odds, target_amount, max_steps=30):
    """Generate the full projected ladder from start_stake to target_amount."""
    rows = []
    stake = start_stake
    for step in range(1, max_steps + 1):
        payout = round(stake * target_odds, 2)
        rows.append({"step": step, "stake": round(stake, 2), "payout": payout})
        if target_amount and payout >= target_amount:
            break
        stake = payout
    return rows
