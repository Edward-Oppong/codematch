import json

from conftest import future, upload


def test_game_page_tabs_and_other_markets(client, arsenal):
    upload(client, json.dumps({"bizCode": 10000, "data": future(arsenal)}))
    html = client.get("/games/sr:match:72221292").get_data(as_text=True)
    assert "?fam=shots" in html and "?fam=other" in html          # only families the game has, plus other markets
    html = client.get("/games/sr:match:72221292?fam=shots").get_data(as_text=True)
    assert "Total Shots: Over" in html
    html = client.get("/games/sr:match:72221292?fam=other&group=Players&q=saka").get_data(as_text=True)
    assert "Saka" in html and len(html) < 400_000


def test_times_can_switch_to_local(client, arsenal):
    upload(client, json.dumps({"bizCode": 10000, "data": future(arsenal)}))
    html = client.get("/games/").get_data(as_text=True)
    assert '<time data-ms="' in html and 'id="tz"' in html and 'id="theme"' in html


def test_empty_codes_page_guides_first_steps(client):
    html = client.get("/").get_data(as_text=True)
    assert 'class="start"' in html and "Fetch codes from Code Hub, or paste your own" in html


def test_chance_hero(client, arsenal):
    from test_fixtures_across_codes import multi_code
    games = []
    for i in range(6):
        g = future(arsenal, hours=3 + i)
        g["eventId"], g["homeTeamName"], g["awayTeamName"] = f"sr:match:{40 + i}", f"H{i}", f"A{i}"
        games.append(g)
    upload(client, json.dumps(multi_code("HERO6", [(g, "18", "total=2.5", "Over 2.5") for g in games])))
    html = client.get("/code/HERO6").get_data(as_text=True)
    assert 'class="odds-in">1 in ' in html                       # 0.525^6 is about 1 in 48
    assert 'role="img" aria-label="2 dots filled out of 100"' in html
