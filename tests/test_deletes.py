import json
import re

from conftest import future, make_league, upload
from test_fixtures_across_codes import multi_code
from test_results import finished


def _two_leagues(client, arsenal):
    a = future(arsenal, hours=-5)
    b = future(arsenal, hours=6)
    b["eventId"], b["homeTeamName"], b["awayTeamName"] = "sr:match:2", "Chelsea", "Spurs"
    c = future(arsenal, hours=7)
    c["eventId"], c["homeTeamName"], c["awayTeamName"] = "sr:match:3", "Roma", "Lazio"
    c["sport"]["category"] = {"id": "sr:category:31", "name": "Italy",
                              "tournament": {"id": "sr:tournament:23", "name": "Serie A"}}
    upload(client, json.dumps(make_league([a, b])))
    upload(client, json.dumps(make_league([c], tid="sr:tournament:23", name="Serie A")))
    return a, b, c


def test_delete_one_game_and_one_league(client, arsenal):
    a, b, c = _two_leagues(client, arsenal)
    r = client.post("/games/delete", data={"event_id": "sr:match:2", "back": "/leagues/sr:tournament:17"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/leagues/sr:tournament:17")
    assert client.get("/games/sr:match:2").status_code == 404
    assert client.get("/games/sr:match:72221292").status_code == 200
    client.post("/leagues/delete", data={"tid": "sr:tournament:17"})
    assert client.get("/games/sr:match:72221292").status_code == 404
    assert client.get("/games/sr:match:3").status_code == 200              # the other league is untouched


def test_mark_and_undo_on_the_code_review(client, arsenal):
    a, b, _ = _two_leagues(client, arsenal)
    upload(client, json.dumps({"bizCode": 10000, "data": a}))
    upload(client, json.dumps(multi_code("MIX2", [(a, "1", "", "Home"), (a, "166", "total=9.5", "Over 9.5")])))
    upload(client, json.dumps(finished(a, (1, 0), (0, 0))))
    html = client.get("/code/MIX2").get_data(as_text=True)
    assert "<b>Won</b>" in html and "Result?" in html and "still to settle" in html
    key = re.search(r'name="sel_key" value="([^"]+)"', html).group(1)
    r = client.post("/results/leg", data={"code": "MIX2", "sel_key": key, "status": "lost", "back": "/code/MIX2"})
    assert r.headers["Location"].endswith("/code/MIX2")
    html = client.get("/code/MIX2").get_data(as_text=True)
    assert "This code has lost." in html and "marked by hand" in html and "Undo" in html
    client.post("/results/leg", data={"code": "MIX2", "sel_key": key, "status": "", "back": "/code/MIX2"})
    assert "Result?" in client.get("/code/MIX2").get_data(as_text=True)


def test_back_never_leaves_the_app(client):
    r = client.post("/games/delete", data={"event_id": "x", "back": "https://evil.example/"})
    assert r.headers["Location"].endswith("/games/")
    r = client.post("/games/delete", data={"event_id": "x", "back": "//evil.example/"})
    assert r.headers["Location"].endswith("/games/")


def test_delete_bet_record_needs_typing_delete(client, arsenal):
    upload(client, json.dumps(multi_code("REC1", [(future(arsenal), "1", "", "Home")])))
    client.post("/results/bet", data={"code": "REC1", "stake": "4"})
    html = client.post("/results/clear", data={"confirm": "yes"}).get_data(as_text=True)
    assert "Nothing deleted" in html and "REC1" in html
    html = client.post("/results/clear", data={"confirm": "delete"}).get_data(as_text=True)
    assert "Deleted your bet record (1 bet)" in html and "No bets recorded" in html


def test_new_key_retires_the_old_bookmark(client):
    from test_bridge import _key
    old = _key(client)
    assert "New key made" in client.post("/import/new-key").get_data(as_text=True)
    new = _key(client)
    assert new != old
    sb = {"Origin": "https://www.sportybet.com"}
    assert client.get(f"/bridge/job?k={old}", headers=sb).status_code == 403
    assert client.get(f"/bridge/job?k={new}", headers=sb).status_code == 200


def test_other_websites_cannot_submit_forms(client):
    for url, data in (("/import/clear", {"what": "everything"}), ("/codes/delete", {"all": "1"}),
                      ("/results/clear", {"confirm": "DELETE"}), ("/import/new-key", {})):
        assert client.post(url, data=data, headers={"Origin": "https://evil.example"}).status_code == 403, url
    assert client.post("/import/clear", data={"what": "old_games"},
                       headers={"Origin": "http://localhost"}).status_code == 200
