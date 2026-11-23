import json
import re

from conftest import future, make_league, upload


def _games(arsenal, n, tid="sr:tournament:17", name="Premier League", start=0):
    out = []
    for i in range(n):
        g = future(arsenal, hours=5 + i)
        g["eventId"], g["homeTeamName"], g["awayTeamName"] = f"sr:match:{500 + start + i}", f"H{start + i}", f"A{start + i}"
        g["sport"]["category"] = {"id": "c", "name": "X", "tournament": {"id": tid, "name": name}}
        out.append(g)
    return out


def test_target_chance_cuts_the_list(client, arsenal):
    upload(client, json.dumps(make_league(_games(arsenal, 8))))
    html = client.get("/leagues/?zone=low&fam=goals&upcoming=1&target=60").get_data(as_text=True)
    n = int(re.search(r"Picks that fit your 60% target</span><b[^>]*>(\d+) of 8", html).group(1))
    assert 1 <= n < 8
    assert html.count('class="cut"') == 1 and "Stop here for 60%" in html
    assert html.count('<tr class="past">') == 8 - n
    # ranked by smallest margin, the code is still built most likely first
    html = client.get("/leagues/?zone=medium&by=return&fam=goals&upcoming=1&target=50").get_data(as_text=True)
    assert "Picks that fit your 50% target</span><b>none" not in html
    html = client.get("/leagues/?zone=low&fam=goals&upcoming=1&target=99.9").get_data(as_text=True)
    assert "Even the most likely single pick wins less often" in html


def test_league_filter(client, arsenal):
    upload(client, json.dumps(make_league(_games(arsenal, 2))))
    upload(client, json.dumps(make_league(_games(arsenal, 3, "sr:tournament:23", "Serie A", start=10),
                                          tid="sr:tournament:23", name="Serie A")))
    html = client.get("/leagues/?upcoming=1").get_data(as_text=True)
    assert "5 games from" in html and "all shown" in html
    html = client.get("/leagues/?upcoming=1&tid=sr:tournament:23").get_data(as_text=True)
    assert "3 games from" in html and "Show all" in html
    href = re.search(r'<a href="([^"]+)">Show all</a>', html).group(1).replace("&amp;", "&")
    assert "tid=" not in href and "upcoming=1" in href
    html = client.get("/games/?tid=sr:tournament:17").get_data(as_text=True)
    assert "H0 v A0" in html and "H10 v A10" not in html


def test_picker_queues_the_ticked_leagues(client):
    directory = {"bizCode": 10000, "data": {"sportList": [{"categories": [
        {"name": "England", "eventSize": 21, "tournaments": [{"id": "sr:tournament:17", "name": "Premier League",
                                                               "eventSize": 21, "categoryName": "England"}]}]}]}}
    upload(client, json.dumps(directory))
    html = client.get("/leagues/").get_data(as_text=True)
    assert 'data-cm-queue="/leagues/queue"' in html
    r = client.post("/leagues/queue", data={"tid": ["sr:tournament:17"]})
    job = client.get(f"/bridge/status?job={r.get_json()['id']}").get_json()
    assert job["status"] == "waiting" and job["total"] == 1
    assert client.post("/leagues/queue", data={}).status_code == 400
