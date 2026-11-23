"""Code Hub: SportyBet's list of shared codes, imported in one response with every pick in it."""
import datetime
import json
import os

from conftest import FIX, make_code, upload

from app.sources.sportybet import snippets
from app.sources.sportybet.parse import classify, parse_hub


def hub_text():
    return open(os.path.join(FIX, "codehub.json"), encoding="utf-8").read()


def test_classify_and_parse():
    body = json.loads(hub_text())
    assert classify(body) == "hub"
    got, skipped = parse_hub(body)
    assert len(got) == 16 and skipped == 4         # the orderType 4 codes aren't accumulators
    assert "D7JH33" not in {c["code"] for c in got}
    import math
    listed = {c["shareCode"]: c["totalOdds"] for c in body["data"]}
    for c in got:                                   # the kept ones: legs multiply to the listed total (odds drift a little)
        assert abs(math.prod(l["odds"] for l in c["sels"]) / listed[c["code"]] - 1) < 0.05
    first = got[0]
    assert first["code"] == "D7PZMN" and len(first["sels"]) == 3
    leg = first["sels"][0]
    # same key format as a code fetched by hand: event|market|specifier|outcome, ids as text
    assert leg["sel_key"] == "sr:match:74165954|60100||3"
    assert leg["market_id"] == "60100" and leg["outcome_id"] == "3"
    assert abs(leg["prob"] - 0.2146318588) < 1e-9 and leg["odds"] == 4.42
    lazio = next(l for c in got for l in c["sels"] if l["market"] == "Lazio Over/Under")
    assert lazio["pick_type"] == "Away Over/Under: Over 0.5" and lazio["specifier"] == "total=0.5"


def test_import_saves_every_code_without_user_ids(client, app):
    out = upload(client, hub_text(), "codehub.json")
    assert "Code Hub: saved 16 codes (16 new); left out 4" in out
    from app.db import connect
    con = connect(app.config["DB_PATH"])
    rows = con.execute("SELECT code, source, popularity, n_selections FROM codes").fetchall()
    assert len(rows) == 16 and all(r["source"] == "hub" for r in rows)
    assert {r["code"]: r["popularity"] for r in rows}["D7YYMC"] == 47
    dump = "\n".join(con.iterdump())
    assert "puid" not in dump                 # the creators' user ids are never kept
    again = upload(client, hub_text(), "codehub.json")
    assert "(0 new)" in again


def test_hand_fetch_keeps_code_hub_label(client, app, arsenal):
    upload(client, hub_text())
    upload(client, json.dumps(make_code("D7PZMN", arsenal, [("1", "", "1")])))
    from app.db import connect
    r = connect(app.config["DB_PATH"]).execute("SELECT source, popularity, n_selections FROM codes WHERE code='D7PZMN'").fetchone()
    assert (r["source"], r["popularity"], r["n_selections"]) == ("hub", 1, 1)


def test_codes_page_filters_and_sorts(client, arsenal, monkeypatch):
    # the Code Hub games kick off on 18 Oct 2026; look at the page as it was the day before
    import app.routes as routes
    monkeypatch.setattr(routes, "now_ms", lambda: 1792195200000)
    upload(client, hub_text())
    upload(client, json.dumps(make_code("MINE01", arsenal, [("1", "", "1")])))
    table = lambda q: client.get(q).get_data(as_text=True).split('id="del"')[1].split("</form>")[0]
    page = table("/?src=hub&sort=ret")
    assert "MINE01" not in page and "D7PZMN" in page and "Code Hub" in page
    # ordered by back per 1, highest first
    assert page.index("D49KYV") < page.index("D4QAGN") < page.index("D9F8VL")
    mine = table("/?src=mine")
    assert "MINE01" in mine and "D7PZMN" not in mine


def test_delete_code_hub_codes_keeps_mine(client, arsenal):
    upload(client, hub_text())
    upload(client, json.dumps(make_code("MINE01", arsenal, [("1", "", "1")])))
    client.post("/codes/delete", data={"all": "hub"})
    page = client.get("/").get_data(as_text=True)
    assert "MINE01" in page and "D7PZMN" not in page


def test_fixtures_across_hub_codes(client):
    upload(client, hub_text())
    page = client.get("/codes/fixtures?all=1").get_data(as_text=True)
    assert "Fiorentina v Como 1907" in page and "Malaga CF v Real Sociedad" in page


def test_hub_requests():
    snip = snippets.hub_snippet(days=3, pages=2, odds=(2, 10.5), legs=(2, 5), today=datetime.date(2026, 10, 18))
    assert len(snip.requests) == 2 and all(r["url"] == snippets.HUB_API for r in snip.requests)
    b0, b1 = (json.loads(r["body"]) for r in snip.requests)
    assert b0["timeFilter"] == [1792281600, 1792368000, 1792454400]     # what SportyBet's own page sent
    assert (b0["i"], b1["i"]) == (0, 1)
    assert b0["oddsFilter"] == [2, 11] and b0["foldsFilter"] == [2, 5]
    assert b0["sortBy"] == {"index": 0, "field": "popularity", "order": "desc"}
    default = json.loads(snippets.hub_snippet(today=datetime.date(2026, 10, 18)).requests[0]["body"])
    assert default["oddsFilter"] == [1, 2147483647] and default["foldsFilter"] == [1, 50]


def test_hub_form_queues_fetch(client):
    page = client.post("/codes/hub", data={"days": "2", "pages": "1"}).get_data(as_text=True)
    assert "bookingCode/filter" in page and "Fetch the Code Hub in your browser" in page


def test_league_names(client, app, arsenal):
    upload(client, hub_text())
    from app.db import connect
    con = connect(app.config["DB_PATH"])
    names = dict(con.execute("SELECT event_id, league FROM selections").fetchall())
    assert names["sr:match:72221328"] == "England Premier League"       # bundled name
    assert names["sr:match:72936090"] == "Greece Super League"
    # a league not bundled keeps its id until the league list or one of its games arrives
    con.execute("UPDATE selections SET league='sr:tournament:999' WHERE event_id='sr:match:72936090'")
    con.commit()
    page = client.get("/codes/fixtures?all=1&min=1").get_data(as_text=True)
    assert "sr:tournament:999" not in page
    directory = {"bizCode": 10000, "data": {"sportList": [{"categories": [
        {"name": "Greece", "tournaments": [{"id": "sr:tournament:999", "name": "Cup"}]}]}]}}
    upload(client, json.dumps(directory))
    con = connect(app.config["DB_PATH"])
    assert con.execute("SELECT league FROM selections WHERE event_id='sr:match:72936090'").fetchone()[0] == "Greece Cup"


def future_hub(hours=24):
    import time
    body = json.loads(hub_text())
    for c in body["data"]:
        for d in c["shareCodeDetail"]:
            d["startTime"] = int(time.time() * 1000) + hours * 3600 * 1000
    return body


def test_button_fetches_the_codes_games_in_same_trip(client):
    from test_bridge import SB, _key
    k = _key(client)
    r = client.post("/codes/hub/queue", data={"days": "3", "pages": "1", "games": "1"})
    job = r.get_json()
    assert job["n"] == 1
    got = client.get(f"/bridge/job?v=3&k={k}", headers=SB).get_json()
    assert "bookingCode/filter" in got["requests"][0]["url"]
    x = client.post(f"/bridge/import?job={job['id']}&k={k}", headers=SB, data=json.dumps(future_hub())).get_json()
    eids = {e for c in parse_hub(future_hub())[0] for l in c["sels"] for e in [l["event_id"]]}
    assert len(x["add"]) == len(eids) and all("factsCenter/event" in a["url"] for a in x["add"])
    # the same list again adds nothing more
    x2 = client.post(f"/bridge/import?job={job['id']}&k={k}", headers=SB, data=json.dumps(future_hub())).get_json()
    assert x2["add"] == []
    st = client.get(f"/bridge/status?job={job['id']}").get_json()
    assert st["total"] == 1 + len(eids)


def test_no_games_without_the_tick(client):
    from test_bridge import SB, _key
    k = _key(client)
    job = client.post("/codes/hub/queue", data={"days": "3", "pages": "1"}).get_json()
    client.get(f"/bridge/job?v=3&k={k}", headers=SB)
    x = client.post(f"/bridge/import?job={job['id']}&k={k}", headers=SB, data=json.dumps(future_hub())).get_json()
    assert x["add"] == []


def test_bookmark_takes_added_requests():
    code = snippets.bookmarklet("http://127.0.0.1:5000/", "key")
    from urllib.parse import unquote
    assert "R.push(...x.add)" in unquote(code) and snippets.BUTTON_VERSION == "3"


def test_codes_page_best_panel_and_cleanup(client, app):
    upload(client, json.dumps(future_hub()))
    page = client.get("/").get_data(as_text=True)
    assert "Best right now" in page and "Built from the fixtures they share" in page
    assert "Picks in more than one code" not in page
    similar = page.split('<details class="similar">')[1]
    assert similar.count("<tr>") - 1 <= 10                           # similar codes: top 10 pairs only
    assert "<details class=\"similar\">" in page
    # the panel's target odds are remembered
    client.get("/?goal=5")
    assert 'name="goal" type="number" min="1.01" step="0.01" value="5"' in client.get("/").get_data(as_text=True)


def test_finished_hub_codes_leave_the_list_then_are_purged(client, app):
    from app import store
    from app.db import connect
    upload(client, hub_text())                       # these games kicked off days ago (in the real export)
    con = connect(app.config["DB_PATH"])
    import time
    now = int(time.time() * 1000)
    con.execute("UPDATE selections SET start_ms=? WHERE code='D7YYMC'", (now - 5 * 3600 * 1000,))
    con.execute("UPDATE selections SET start_ms=? WHERE code<>'D7YYMC'", (now - 40 * 86400 * 1000,))
    con.commit()
    store.add_bet(con, "D4QAGN", 10)                 # a code with a bet is never purged
    page = client.get("/").get_data(as_text=True)
    left = {r[0] for r in connect(app.config["DB_PATH"]).execute("SELECT code FROM codes")}
    assert left == {"D7YYMC", "D4QAGN"}
    assert 'href="/code/D7YYMC"' not in page and "2 finished Code Hub codes left this" in page


def test_fixtures_min_legs_and_odds_from_code(client):
    import re
    upload(client, json.dumps(future_hub()))
    n_legs = lambda page: int(re.search(r"Together \((\d+) leg", page).group(1))
    one = client.get("/codes/fixtures?odds=2").get_data(as_text=True)
    assert n_legs(one) == 1 and "from this pick</button>" in one
    three = client.get("/codes/fixtures?odds=2&minlegs=3").get_data(as_text=True)
    assert n_legs(three) >= 3 and "these 3 picks" in three
    assert "odds from code" in three and "use the odds saved with the codes, fetched" in three


def test_best_with_min_legs_matches_brute_force():
    import itertools
    import math
    import random
    from app.analysis import target
    rnd = random.Random(3)
    games = [[{"odds": round(1 + rnd.random() * 2, 2), "prob": 0} for _ in range(3)] for _ in range(6)]
    for g in games:
        for c in g:
            c["prob"] = min(0.97, 0.93 / c["odds"])
    for goal, k in ((2.0, 3), (4.0, 2), (3.0, 4)):
        best = None
        for n in range(k, 7):
            for gs in itertools.combinations(range(6), n):
                for pick in itertools.product(*(games[i] for i in gs)):
                    if math.prod(c["odds"] for c in pick) >= goal:
                        p = math.prod(c["prob"] for c in pick)
                        best = p if best is None or p > best else best
        got = target.best_with_min_legs(games, goal, k)
        assert len(got) >= k and abs(math.prod(c["prob"] for c in got) - best) < 0.01 * best


def test_hub_record_maths():
    from app.analysis.settle import hub_record
    cs = [{"popularity": 10, "status": "won", "multiplier": 4.0, "prob": 0.25, "ret": 0.9}] + \
         [{"popularity": 10, "status": "lost", "multiplier": 0, "prob": 0.25, "ret": 0.9}] * 3 + \
         [{"popularity": 1, "status": "lost", "multiplier": 0, "prob": 0.5, "ret": 0.95}] * 2 + \
         [{"popularity": 1, "status": "pending", "multiplier": 0, "prob": 0.5, "ret": 0.95}]
    rec = {g["key"]: g for g in hub_record(cs)}
    assert (rec["all"]["n"], rec["all"]["won"]) == (6, 1)
    assert rec["popular"]["expected"] == 1.0 and rec["popular"]["returned"] == 4.0
    assert abs(rec["rest"]["ret_expected"] - 1.9) < 1e-9 and rec["rest"]["low"] == 0.0


def test_results_page_track_record(client, app):
    from app.db import connect
    upload(client, hub_text())                               # real games, all played by now
    con = connect(app.config["DB_PATH"])
    # Nottingham Forest 0:2 Arsenal, Brighton 0:1 Crystal Palace (2:0 at half time... kept simple: 0:1)
    con.execute("INSERT INTO results VALUES('sr:match:72221328', 0, 1, 0, 1, 0)")
    con.execute("INSERT INTO results VALUES('sr:match:72221316', 0, 0, 0, 1, 0)")
    con.commit()
    page = client.get("/results/").get_data(as_text=True)
    assert "Code Hub track record" in page and "Every Code Hub code" in page
    # Brighton home (2UP) lost 0:1 without Brighton scoring: D7YYMC, D4QAGN, CZ9CYD and D75H9S (handicap) are lost
    import re
    row = re.search(r"Every Code Hub code<td[^>]*>(\d+)", page)
    assert row and int(row.group(1)) >= 3
    assert "Legs to mark by hand" not in page                 # unplayed Code Hub legs don't fill that list


def test_track_record_outlives_purged_codes(client, app):
    import time
    from app.db import connect
    upload(client, hub_text())
    con = connect(app.config["DB_PATH"])
    con.execute("INSERT INTO results VALUES('sr:match:72221316', 0, 0, 0, 1, 0)")    # Brighton 0:1 Palace
    con.execute("UPDATE selections SET start_ms=?", (int(time.time() * 1000) - 40 * 86400 * 1000,))
    con.commit()
    client.get("/")                                         # records the outcomes, then purges the old codes
    con = connect(app.config["DB_PATH"])
    assert con.execute("SELECT COUNT(*) FROM codes").fetchone()[0] == 0
    n = con.execute("SELECT COUNT(*) FROM hub_outcomes WHERE status='lost'").fetchone()[0]
    assert n >= 3
    assert "Every Code Hub code" in client.get("/results/").get_data(as_text=True)
    client.post("/results/clear", data={"confirm": "DELETE"})
    assert connect(app.config["DB_PATH"]).execute("SELECT COUNT(*) FROM hub_outcomes").fetchone()[0] == 0
