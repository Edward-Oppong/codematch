import json
import sqlite3

from conftest import future, make_code, make_league, upload

from app.sources.sportybet import snippets
from app.sources.sportybet.importer import extract_all_json


def test_several_responses_in_one_file(client, arsenal):
    other = future(arsenal)
    other["eventId"] = "sr:match:1"
    text = json.dumps({"bizCode": 10000, "data": arsenal}) + "\n" + json.dumps({"bizCode": 10000, "data": other})
    html = upload(client, text)
    assert html.count("saved 1347 markets") == 2


def test_league_import_does_not_replace_full_game(client, arsenal):
    upload(client, json.dumps({"bizCode": 10000, "data": arsenal}))
    slim = dict(arsenal, markets=arsenal["markets"][:40])
    html = upload(client, json.dumps(make_league([slim])))
    assert "League Premier League: saved 1 games" in html
    assert "kept the fuller copy" not in html          # league messages summarise; the game itself is kept
    r = client.get("/games/sr:match:72221292")
    assert "1347 markets" in r.get_data(as_text=True)


def test_code_import_and_review(client, arsenal):
    upload(client, json.dumps(make_code("ABC123", arsenal, [("19", "total=1.5", "12")])))
    html = client.get("/").get_data(as_text=True)
    assert "ABC123" in html
    r = client.get("/code/ABC123").get_data(as_text=True)
    assert "game not imported" in r and "Fetch those games" in r
    upload(client, json.dumps({"bizCode": 10000, "data": arsenal}))
    r = client.get("/code/ABC123").get_data(as_text=True)
    assert "Home Excluded Goals: 1" in r                # a safer alternative is offered (Arsenal not exactly 1)
    assert "Medium" in r                                # 1.57 sits in the medium zone


def test_har_reads_only_responses(client, arsenal):
    har = {"log": {"entries": [
        {"request": {"headers": [{"name": "cookie", "value": "secret"}]},
         "response": {"content": {"text": json.dumps({"bizCode": 10000, "data": arsenal})}}},
        {"response": {"content": {"text": "<html></html>"}}}]}}
    html = upload(client, json.dumps(har), "session.har")
    assert "HAR file: read 2 responses and imported 1 games" in html


def test_old_database_is_upgraded(tmp_path, arsenal):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript("""
      CREATE TABLE codes(code TEXT PRIMARY KEY, fetched_at INTEGER, n_selections INTEGER);
      CREATE TABLE selections(code TEXT, sel_key TEXT, event_id TEXT, match TEXT, league TEXT, market TEXT,
                              pick TEXT, odds REAL, start_ms INTEGER, PRIMARY KEY(code, sel_key));
      CREATE TABLE blobs(key TEXT PRIMARY KEY, kind TEXT, saved_at INTEGER, n INTEGER, name TEXT, body TEXT);""")
    con.execute("INSERT INTO blobs VALUES(?,?,?,?,?,?)",
                ("event:" + arsenal["eventId"], "event", 1, 1347, "Arsenal v Leeds United", json.dumps(arsenal)))
    con.commit()
    con.close()
    from app.db import connect
    con = connect(str(path))
    row = con.execute("SELECT tournament_id, n_markets FROM events").fetchone()
    assert tuple(row) == ("sr:tournament:17", 1347)
    assert con.execute("SELECT COUNT(*) FROM blobs WHERE kind='event'").fetchone()[0] == 0
    assert "prob" in {r["name"] for r in con.execute("PRAGMA table_info(selections)")}


def test_snippets_carry_ids():
    s = snippets.events_snippet([("sr:match:72221292", "Arsenal v Leeds")])
    assert "sr%3Amatch%3A72221292" in s and "cleanFetch" in s
    s = snippets.leagues_snippet([("sr:tournament:17", "England Premier League"), ("sr:tournament:23", "Serie A")])
    assert s.count("pcEvents") == 2 and "900304" in s and "leagues_2.json" in s


def test_extract_ignores_text_around_json():
    docs = extract_all_json('Request URL: x\ncookie: abc\n{"a": 1}\nmore text [1, 2]')
    assert docs == [{"a": 1}, [1, 2]]
