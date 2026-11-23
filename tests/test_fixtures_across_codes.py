import re
import json
import random
import time

from conftest import future, upload


def multi_code(code, legs):
    """A booking-code response with legs [(game, market id, specifier, outcome text)] across several games."""
    sels, outs = [], {}
    for ev, mid, spec, desc in legs:
        m = next(m for m in ev["markets"] if m["id"] == mid and (m.get("specifier") or "") == spec)
        o = next(o for o in m["outcomes"] if o["desc"] == desc)
        sels.append({"eventId": ev["eventId"], "marketId": mid, "specifier": spec, "outcomeId": o["id"]})
        game = outs.setdefault(ev["eventId"], {**{k: ev[k] for k in ("eventId", "homeTeamName", "awayTeamName",
                                                                   "estimateStartTime", "sport")}, "markets": []})
        if m not in game["markets"]:
            game["markets"].append(m)
    return {"bizCode": 10000, "data": {"shareCode": code, "ticket": {"selections": sels}, "outcomes": list(outs.values())}}


PICKS = [("1", "", "Home"), ("10", "", "Home or Draw"), ("18", "total=1.5", "Over 1.5"), ("11", "", "Home"),
         ("19", "total=0.5", "Over 0.5"), ("1", "", "Away"), ("29", "", "Yes")]


def test_twenty_codes(client, arsenal):
    games = []
    for i in range(6):
        g = future(arsenal, hours=10 + i)
        g["eventId"] = f"sr:match:{900 + i}"
        g["homeTeamName"], g["awayTeamName"] = f"Home{i}", f"Away{i}"
        games.append(g)
    for g in games[:4]:                                     # two games stay un-imported
        upload(client, json.dumps({"bizCode": 10000, "data": g}))
    rnd = random.Random(7)
    for c in range(20):
        chosen = rnd.sample(games, 4)
        legs = [(g, *rnd.choice(PICKS)) for g in chosen]
        upload(client, json.dumps(multi_code(f"CODE{c:02d}", legs)))
    t = time.time()
    html = client.get("/codes/fixtures").get_data(as_text=True)
    assert time.time() - t < 3
    assert html.count('class="fixture"') >= 6               # every game is in 2+ of 20 codes
    assert "Codes disagree" in html                         # Home vs Away on the same game
    assert "Common ground" in html
    assert "aren't imported" in html and "Fetch those games" in html
    html = client.get("/codes/fixtures?use=common&n=3").get_data(as_text=True)
    assert "Together (3 legs)" in html
    t = time.time()
    assert client.get("/").status_code == 200               # 190 code pairs compared
    assert time.time() - t < 3


def test_common_ground_covers_the_chosen_picks(client, arsenal):
    g = future(arsenal)
    upload(client, json.dumps({"bizCode": 10000, "data": g}))
    upload(client, json.dumps(multi_code("AAA", [(g, "1", "", "Home")])))
    upload(client, json.dumps(multi_code("BBB", [(g, "19", "total=1.5", "Over 1.5")])))
    html = client.get("/codes/fixtures").get_data(as_text=True)
    assert "in 2 codes" in html and "No contradictions" in html
    from app.analysis import markets
    priced = markets.build_priced(g, "goals")
    label = html.split("Common ground: <b>")[1].split("</b>")[0].replace("&amp;", "&")
    v = priced[label]
    assert markets.covers(v, priced["1X2: Home"]) and markets.covers(v, priced["Home Total: Over 1.5"])


def _twenty(client, arsenal):
    games = []
    for i in range(6):
        g = future(arsenal, hours=10 + i)
        g["eventId"] = f"sr:match:{900 + i}"
        g["homeTeamName"], g["awayTeamName"] = f"Home{i}", f"Away{i}"
        games.append(g)
        upload(client, json.dumps({"bizCode": 10000, "data": g}))
    rnd = random.Random(7)
    for c in range(20):
        legs = [(g, *rnd.choice(PICKS)) for g in rnd.sample(games, 4)]
        upload(client, json.dumps(multi_code(f"CODE{c:02d}", legs)))


def test_highest_chance_for_odds_beats_stacking(client, arsenal):
    _twenty(client, arsenal)
    html = client.get("/codes/fixtures?use=target&odds=2&n=").get_data(as_text=True)
    assert "Highest chance for odds of 2" in html and "Make a SportyBet booking code" in html
    best = float(html.split("Highest chance for odds of 2</span><b class=\"\">")[1].split("%")[0])
    if "Stacking the safest picks instead</span><b" in html:
        stacked = float(html.split("Stacking the safest picks instead</span><b class=\"\">")[1].split("%")[0])
        assert best >= stacked
    total = float(html.split('<tr class="total">')[1].split('class="num">')[1].split("<")[0])
    assert total >= 1.99
    # every leg can go into a SportyBet code
    n_legs = int(html.split("Together (")[1].split(" ")[0])
    recommended = html.split("A code from these fixtures")[1].split('id="each-fixture"')[0]
    assert recommended.count('name="sel"') == n_legs


def test_agree_only_and_make_code(client, arsenal):
    games = []
    for i in range(4):
        g = future(arsenal, hours=10 + i)
        g["eventId"] = f"sr:match:{800 + i}"
        g["homeTeamName"], g["awayTeamName"] = f"Home{i}", f"Away{i}"
        games.append(g)
        upload(client, json.dumps({"bizCode": 10000, "data": g}))
    # codes agree on games 0 to 2; on game 3 one code says Home and another Away
    upload(client, json.dumps(multi_code("AAA", [(games[0], "1", "", "Home"), (games[1], "18", "total=1.5", "Over 1.5"),
                                                 (games[2], "10", "", "Home or Draw"), (games[3], "1", "", "Home")])))
    upload(client, json.dumps(multi_code("BBB", [(games[0], "10", "", "Home or Draw"), (games[1], "18", "total=1.5", "Over 1.5"),
                                                 (games[2], "1", "", "Home"), (games[3], "1", "", "Away")])))
    html = client.get("/codes/fixtures?use=safest&agree=1&n=").get_data(as_text=True)
    assert "contradict each other (3)" in html and "Together (3 legs)" in html
    assert "Home3 v Away3</a><td" not in html.split("Each fixture")[0]
    recommended = html.split("A code from these fixtures")[1].split('id="each-fixture"')[0]
    sels = re.findall(r"name=\"sel\"[^>]*?value='([^']+)'", recommended)
    assert len(sels) == 3
    r = client.post("/codes/make", data={"sel": [s.replace("&#34;", '"') for s in sels]})
    assert r.status_code == 200 and r.get_json()["id"]
    page = client.get("/codes/fixtures?use=safest&n=").get_data(as_text=True)
    assert "Together (4 legs)" in page


def test_unreachable_odds(client, arsenal):
    _twenty(client, arsenal)
    html = client.get("/codes/fixtures?use=target&odds=100000&n=2").get_data(as_text=True)
    assert "reaches odds of" in html
