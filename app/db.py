"""SQLite database: one connection per request, schema created and upgraded on first use."""
import json
import os
import sqlite3

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS codes(code TEXT PRIMARY KEY, fetched_at INTEGER, n_selections INTEGER, source TEXT,
    popularity INTEGER);
CREATE TABLE IF NOT EXISTS selections(
    code TEXT, sel_key TEXT, event_id TEXT, match TEXT, league TEXT,
    market TEXT, pick TEXT, odds REAL, start_ms INTEGER,
    market_id TEXT, specifier TEXT, outcome_id TEXT, prob REAL, pick_type TEXT,
    PRIMARY KEY(code, sel_key));
CREATE INDEX IF NOT EXISTS sel_code ON selections(code);
CREATE INDEX IF NOT EXISTS sel_start ON selections(start_ms);
CREATE INDEX IF NOT EXISTS sel_ev ON selections(event_id);
CREATE TABLE IF NOT EXISTS blobs(key TEXT PRIMARY KEY, kind TEXT, saved_at INTEGER, n INTEGER, name TEXT, body TEXT);
CREATE TABLE IF NOT EXISTS events(
    event_id TEXT PRIMARY KEY, tournament_id TEXT, tournament TEXT, category TEXT, home TEXT, away TEXT,
    start_ms INTEGER, n_markets INTEGER, saved_at INTEGER, body TEXT);
CREATE INDEX IF NOT EXISTS events_start ON events(start_ms);
CREATE INDEX IF NOT EXISTS events_tour ON events(tournament_id);
CREATE TABLE IF NOT EXISTS history(event_id TEXT, family TEXT, label TEXT, odds REAL, prob REAL, ts INTEGER);
CREATE INDEX IF NOT EXISTS history_ev ON history(event_id, label);
CREATE INDEX IF NOT EXISTS history_ts ON history(event_id, ts);
CREATE TABLE IF NOT EXISTS results(
    event_id TEXT PRIMARY KEY, h1 INTEGER, a1 INTEGER, h2 INTEGER, a2 INTEGER, saved_at INTEGER);
CREATE TABLE IF NOT EXISTS leg_results(
    code TEXT, sel_key TEXT, status TEXT, PRIMARY KEY(code, sel_key));
CREATE TABLE IF NOT EXISTS picks(
    event_id TEXT, family TEXT, label TEXT, odds REAL, prob REAL, ret REAL, push INTEGER, cond INTEGER,
    push_prob REAL, refund_on TEXT, mid TEXT, spec TEXT, oid TEXT,
    odesc TEXT, bkey TEXT, cat TEXT, side TEXT, bname TEXT, prob_ok INTEGER, mkt_kept REAL);
CREATE INDEX IF NOT EXISTS picks_ev ON picks(event_id, family);
CREATE INDEX IF NOT EXISTS picks_bkey ON picks(bkey, event_id);
CREATE INDEX IF NOT EXISTS picks_val ON picks(prob_ok, cond, ret, prob);
CREATE TABLE IF NOT EXISTS priced_at(event_id TEXT PRIMARY KEY, saved_at INTEGER, banned INTEGER);
CREATE TABLE IF NOT EXISTS hub_outcomes(
    code TEXT PRIMARY KEY, popularity INTEGER, prob REAL, ret REAL, status TEXT, multiplier REAL, n_legs INTEGER,
    settled_at INTEGER);
CREATE TABLE IF NOT EXISTS bets(
    id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT, stake REAL, placed_at INTEGER, payout REAL);
CREATE TABLE IF NOT EXISTS rollovers(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    start_stake REAL,
    target_odds REAL,
    target_amount REAL,
    current_step INTEGER DEFAULT 0,
    current_stake REAL,
    status TEXT DEFAULT 'active',
    created_at INTEGER,
    updated_at INTEGER);
CREATE TABLE IF NOT EXISTS rollover_steps(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rollover_id INTEGER,
    step INTEGER,
    stake REAL,
    odds REAL,
    result TEXT,
    payout REAL,
    note TEXT,
    played_at INTEGER);
CREATE INDEX IF NOT EXISTS rollover_steps_rid ON rollover_steps(rollover_id);
"""


def _ensure_schema(con):
    """Create schema on fresh database and run upgrades if needed."""
    has_tables = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone()
    if not has_tables:
        _before_schema(con)
        con.executescript(SCHEMA)
    _upgrade(con)


def connect(path):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    con = sqlite3.connect(path, timeout=30.0)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA busy_timeout = 30000")
        con.execute("PRAGMA synchronous = NORMAL")
        con.execute("PRAGMA cache_size = -64000")
        con.execute("PRAGMA temp_store = MEMORY")
        con.execute("PRAGMA mmap_size = 268435456")
    except sqlite3.Error:
        pass
    _ensure_schema(con)
    return con


def _before_schema(con):
    """The saved picks are a cache of each game's prices: when their columns change, drop them (the schema then
    makes them again) and every game is priced again the first time a page needs it."""
    cols = {r["name"] for r in con.execute("PRAGMA table_info(picks)")}
    if cols and "bkey" not in cols:
        con.execute("DROP TABLE picks")
        con.execute("DROP TABLE IF EXISTS priced_at")
        con.commit()


def _upgrade(con):
    """Bring a database from the single-file version of the app up to date."""
    have = {r["name"] for r in con.execute("PRAGMA table_info(selections)")}
    for col, typ in (("market_id", "TEXT"), ("specifier", "TEXT"), ("outcome_id", "TEXT"),
                     ("prob", "REAL"), ("pick_type", "TEXT")):
        if col not in have:
            con.execute(f"ALTER TABLE selections ADD COLUMN {col} {typ}")
    have = {r["name"] for r in con.execute("PRAGMA table_info(codes)")}
    for col, typ in (("source", "TEXT"), ("popularity", "INTEGER")):     # where a code came from (Code Hub)
        if col not in have:
            con.execute(f"ALTER TABLE codes ADD COLUMN {col} {typ}")
    con.execute("CREATE INDEX IF NOT EXISTS codes_src ON codes(source, fetched_at)")
    # the old version kept games as JSON blobs; move them into the events table
    old = con.execute("SELECT key, saved_at, body FROM blobs WHERE kind='event'").fetchall()
    if old:
        from . import store
        leagues = {}
        for r in con.execute("SELECT body FROM blobs WHERE kind='league'"):
            lg = json.loads(r["body"])
            for e in lg.get("events") or [{"eventId": i} for i in lg.get("eventIds", [])]:
                leagues[e["eventId"]] = {"id": lg.get("id"), "name": lg.get("name"), "category": lg.get("category")}
        for r in old:
            ev = json.loads(r["body"])
            store.save_event(con, ev, league=leagues.get(ev.get("eventId")), saved_at=r["saved_at"],
                             history=False, commit=False)
        con.execute("DELETE FROM blobs WHERE kind='event'")
    con.commit()
    # older versions stored every price at every import; drop the repeats once
    if not con.execute("SELECT 1 FROM blobs WHERE key='history_pruned'").fetchone():
        from . import store
        store.prune_history(con)
        con.execute("INSERT OR REPLACE INTO blobs VALUES('history_pruned','meta',0,0,'','true')")
        con.commit()


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DB_PATH"])
    return g.db


def close_db(_exc=None):
    con = g.pop("db", None)
    if con is not None:
        con.close()
