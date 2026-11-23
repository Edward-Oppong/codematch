"""Choosing picks by hand: tick-all, ready-made sets, several codes made in one go, and refreshing the league list."""
import json
import re

from conftest import future, make_league, upload
from test_bridge import SB, _key
from test_fixtures_across_codes import multi_code
from test_target_and_filters import _games

from app.sources.sportybet import snippets


def _directory(*leagues):
    return {"bizCode": 10000, "data": {"sportList": [{"categories": [
        {"name": "England", "eventSize": 30, "tournaments": [
            {"id": tid, "name": name, "eventSize": 10, "categoryName": "England"} for tid, name in leagues]}]}]}}


def test_split_evenly():
    assert [len(p) for p in snippets.split_evenly(list(range(51)), 50)] == [26, 25]
    assert [len(p) for p in snippets.split_evenly(list(range(120)), 40)] == [40, 40, 40]
    assert [len(p) for p in snippets.split_evenly(list(range(7)), 3)] == [3, 2, 2]
    assert snippets.split_evenly([], 50) == []


def test_many_picks_make_several_codes_in_one_trip(client):
    k = _key(client)
    sels = [{"eventId": f"sr:match:{i}", "marketId": "1", "specifier": "", "outcomeId": "1"} for i in range(120)]
    r = client.post("/codes/make", data={"sel": [json.dumps(s) for s in sels], "per_code": "40"}).get_json()
    assert r["codes"] == 3
    job = client.get(f"/bridge/job?v=3&k={k}", headers=SB).get_json()
    makes = [q for q in job["requests"] if q["url"].endswith("/orders/share")]
    assert [len(json.loads(q["body"])["selections"]) for q in makes] == [40, 40, 40]
    assert makes[1]["label"] == "make booking code 2 of 3 (40 picks)"
    for code in ("AAA111", "BBB222", "CCC333"):
        client.post(f"/bridge/import?job={job['id']}&k={k}", headers=SB, content_type="text/plain",
                    data=json.dumps({"bizCode": 10000, "data": {"shareCode": code}}))
    s = client.post(f"/bridge/done?job={job['id']}&k={k}", headers=SB).get_json()
    assert s["summary"] == "Booking codes AAA111, BBB222, CCC333 made on SportyBet."
    html = client.get(f"/bridge/status?job={job['id']}").get_json()["check_html"]
    assert "Codes AAA111, BBB222, CCC333" in html


def test_partly_made_codes_say_so(client):
    k = _key(client)
    sels = [{"eventId": f"sr:match:{i}", "marketId": "1", "specifier": "", "outcomeId": "1"} for i in range(60)]
    jid = client.post("/codes/make", data={"sel": [json.dumps(s) for s in sels]}).get_json()["id"]
    client.get(f"/bridge/job?v=3&k={k}", headers=SB)
    client.post(f"/bridge/import?job={jid}&k={k}", headers=SB, content_type="text/plain",
                data=json.dumps({"bizCode": 10000, "data": {"shareCode": "AAA111"}}))
    client.post(f"/bridge/import?job={jid}&k={k}", headers=SB, content_type="text/plain",
                data=json.dumps({"bizCode": 4200, "message": "Too many selections", "data": None}))
    s = client.post(f"/bridge/done?job={jid}&k={k}", headers=SB).get_json()
    assert s["summary"] == "Booking code AAA111 made on SportyBet."
    html = client.get(f"/bridge/status?job={jid}").get_json()["check_html"]
    assert "only 1 of the 2 codes asked for was made" in html and "Too many selections" in html


def test_league_list_refresh_marks_new_leagues(client):
    upload(client, json.dumps(_directory(("sr:tournament:17", "Premier League"))))
    html = client.get("/leagues/").get_data(as_text=True)
    assert "Refresh the league list from SportyBet" in html and "New since the last refresh" not in html
    msg = upload(client, json.dumps(_directory(("sr:tournament:17", "Premier League"), ("sr:tournament:999", "Winter Cup"))))
    assert "League list refreshed: 2 leagues, 1 new since the last refresh" in msg
    html = client.get("/leagues/").get_data(as_text=True)
    new = html.split("New since the last refresh")[1].split("Top leagues")[0]
    assert "Winter Cup" in new and "Premier League" not in new
    assert 'data-filter="#league-picker label.pick"' in html and "tick all shown" in html
    # the refresh is queued for the button
    r = client.post("/leagues/directory/queue").get_json()
    k = _key(client)
    job = client.get(f"/bridge/job?v=3&k={k}", headers=SB).get_json()
    assert r["n"] == 1 and "popularAndSportList" in job["requests"][0]["url"]


def test_pick_lists_offer_tick_all_and_split(client, arsenal):
    upload(client, json.dumps(make_league(_games(arsenal, 6))))
    html = client.get("/leagues/?zone=low&fam=goals&upcoming=1&todds=2").get_data(as_text=True)
    assert html.count("<input type=\"checkbox\" data-tick-all") == 2 and 'name="per_code"' in html
    best = html.split("Highest chance for odds of 2")[1].split("One pick per game")[0]
    assert re.search(r'name="sel"[^>]*checked[^>]*data-odds="[\d.]+" data-prob="[\d.]+" data-game="sr:match:', best)
    screen = client.get("/leagues/?mode=screen&sent=1&upcoming=1&bt=team_goals|Over+0.5").get_data(as_text=True)
    assert "data-tick-all" in screen and "Make SportyBet booking codes from the ticked selections" in screen


def test_fixtures_can_be_chosen_by_hand(client, arsenal):
    games = []
    for i in range(3):
        g = future(arsenal, hours=10 + i)
        g["eventId"] = f"sr:match:{900 + i}"
        g["homeTeamName"], g["awayTeamName"] = f"Home{i}", f"Away{i}"
        games.append(g)
        upload(client, json.dumps({"bizCode": 10000, "data": g}))
    upload(client, json.dumps(multi_code("AAA", [(games[0], "1", "", "Home"), (games[1], "18", "total=1.5", "Over 1.5"),
                                                 (games[2], "1", "", "Away")])))
    upload(client, json.dumps(multi_code("BBB", [(games[0], "10", "", "Home or Draw"), (games[1], "18", "total=1.5", "Over 1.5"),
                                                 (games[2], "1", "", "Home")])))
    html = client.get("/codes/fixtures?use=safest&n=").get_data(as_text=True)
    each = html.split('id="each-fixture"')[1]
    for kind in ("safest", "popular", "common"):
        assert f'data-tick="{kind}"' in each
    assert each.count("data-safest") == 3 and each.count("data-popular") == 3
    # every pick any code chose can be ticked: 2 on game 0, 1 on game 1, 2 on game 2, plus common-ground picks
    assert len(re.findall(r'name="sel"[^>]*data-game="sr:match:90\d"', each)) >= 5
    # the recommended code's picks come ticked and can be unticked
    rec = html.split("A code from these fixtures")[1].split('id="each-fixture"')[0]
    assert rec.count('name="sel" aria-label="Use this pick" checked') == 3
