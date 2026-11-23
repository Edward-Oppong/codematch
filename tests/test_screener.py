"""Leagues, "choose the bet, find the teams"."""
import copy
import json
import re

from conftest import future, make_league, upload

from app.analysis import bettypes
from app.db import connect


def test_classify():
    c = bettypes.classify
    assert c("Home Total: Over 0.5") == ("team_goals", "team_goals|Over 0.5", "home", "Team over 0.5")
    assert c("Away Total: Over 0.5")[1:3] == ("team_goals|Over 0.5", "away")
    assert c("Away Corners: Under 3.5")[:3] == ("team_corners", "team_corners|Under 3.5", "away")
    assert c("Home Bookings: Over 1.5")[0] == "team_bookings"
    assert c("Total: Over 2.5")[:3] == ("match_goals", "match_goals|Over 2.5", None)
    assert c("BTTS: Yes")[0] == "btts"
    assert c("Double Chance: Home or Draw")[3].startswith("1X") and c("Double Chance: Home or Away")[3].startswith("12")
    # one side named: a team bet in other markets too; both sides: not a team bet
    assert c("1H Home Total: Over 0.5")[1:3] == ("other|1H Team Total: Over 0.5", "home")
    assert c("1X2: Away")[1:3] == ("other|1X2: Team", "away")
    assert c("HT/FT: Home/Away")[2] is None
    # team names in a label mean the same bet in every game
    a = c("HT/FT & Exact Goals: Arsenal/Arsenal & 1", "Arsenal", "Leeds United")
    b = c("HT/FT & Exact Goals: Lazio/Lazio & 1", "Lazio", "Monza")
    assert a[1] == b[1] and a[2] == "home"


def test_market_checks(arsenal):
    chk = bettypes.market_checks(arsenal)
    ok, kept = chk[("1", "")]
    assert ok and 0 < kept < 0.1
    ok, kept = chk[("10", "")]                                # double chance: probabilities add up to 2
    assert ok and kept is not None and 0 < kept < 0.15
    bad = copy.deepcopy(arsenal)
    m = next(m for m in bad["markets"] if m["id"] == "1")
    m["outcomes"][0]["probability"] = str(float(m["outcomes"][0]["probability"]) + 0.3)
    assert bettypes.market_checks(bad)[("1", "")] == (False, None)
    m = next(m for m in bad["markets"] if m["id"] == "29")
    m["outcomes"][0]["isActive"] = 0                          # one outcome off: chances fine, no margin
    assert bettypes.market_checks(bad)[("29", "")] == (True, None)


def _games(arsenal, n=4, broken=None):
    out = []
    for i in range(n):
        g = future(arsenal, hours=5 + i)
        g["eventId"], g["homeTeamName"], g["awayTeamName"] = f"sr:match:{900 + i}", f"Home{i}", f"Away{i}"
        g["sport"]["category"] = {"id": "c", "name": "X", "tournament": {"id": "sr:tournament:17", "name": "PL"}}
        if i == broken:                                       # this game's team-goal probabilities don't add up
            for m in g["markets"]:
                if m["id"] == "19":
                    for o in m["outcomes"]:
                        o["probability"] = str(float(o["probability"]) * 1.2)
        out.append(g)
    return out


def _rows(html):
    part = html.split("The list")[1]
    return re.findall(r'<td><b>([^<]+)</b> <span class="muted">v ([^<]+)</span>.*?data-label="Home or away">([^<\s]+)'
                      r'.*?data-label="Bet">([^<]+?) <span.*?data-label="Odds" class="num">([\d.]+).*?'
                      r'data-label="Chance" class="num">(.*?)\n', part, re.S)


def test_team_list_merges_home_and_away(client, arsenal):
    upload(client, json.dumps(make_league(_games(arsenal))))
    html = client.get("/leagues/?mode=screen&sent=1&upcoming=1&bt=team_goals|Over+0.5").get_data(as_text=True)
    rows = _rows(html)
    assert len(rows) == 8                                     # both teams of 4 games, by name
    assert {r[0] for r in rows} == {f"Home{i}" for i in range(4)} | {f"Away{i}" for i in range(4)}
    assert {r[2] for r in rows} == {"home", "away"}
    assert all(r[1] == (r[0].replace("Home", "Away") if r[2] == "home" else r[0].replace("Away", "Home")) for r in rows)
    chances = [float(r[5].split("%")[0]) for r in rows]
    assert chances == sorted(chances, reverse=True)
    # home teams only
    html = client.get("/leagues/?mode=screen&sent=1&upcoming=1&side=home&bt=team_goals|Over+0.5").get_data(as_text=True)
    assert {r[2] for r in _rows(html)} == {"home"} and len(_rows(html)) == 4
    # odds window
    html = client.get("/leagues/?mode=screen&sent=1&upcoming=1&mino=1.5&bt=team_goals|Over+0.5").get_data(as_text=True)
    assert all(float(r[4]) >= 1.5 for r in _rows(html))


def test_one_per_match_and_contradictions(client, arsenal):
    upload(client, json.dumps(make_league(_games(arsenal, 2))))
    q = "/leagues/?mode=screen&sent=1&upcoming=1&bt=team_goals|Over+0.5&bt=team_goals|Under+0.5"
    everything = _rows(client.get(q).get_data(as_text=True))
    assert len(everything) == 8                               # over and under for both teams of 2 games
    one = _rows(client.get(q + "&one=1").get_data(as_text=True))
    assert len(one) == 2
    noconf = _rows(client.get(q + "&noconf=1").get_data(as_text=True))
    # for each team, over 0.5 and under 0.5 contradict: one of each pair goes
    assert len(noconf) == 4 and len({(r[0]) for r in noconf}) == 4


def test_unreliable_chance_is_not_shown_or_used(client, arsenal):
    upload(client, json.dumps(make_league(_games(arsenal, 3, broken=0))))
    html = client.get("/leagues/?mode=screen&sent=1&upcoming=1&bt=team_goals|Over+0.5").get_data(as_text=True)
    rows = _rows(html)
    home0 = next(r for r in rows if r[0] == "Home0")
    assert "not given" in home0[5]
    assert "has no reliable chance" in html
    # a minimum chance leaves it out, and the search never uses it
    html = client.get("/leagues/?mode=screen&sent=1&upcoming=1&minp=1&bt=team_goals|Over+0.5").get_data(as_text=True)
    assert "<b>Home0</b>" not in html.split("The list")[1]
    html = client.get("/leagues/?mode=screen&sent=1&upcoming=1&bt=team_goals|Over+0.5&todds=1.2&maxlegs=3").get_data(as_text=True)
    assert "<b>Home0</b>" not in html.split("Highest chance for total odds")[1].split("The list")[0]


def test_target_search(client, arsenal):
    upload(client, json.dumps(make_league(_games(arsenal, 5))))
    q = "/leagues/?mode=screen&sent=1&upcoming=1&one=1&bt=team_goals|Over+0.5&bt=match_goals|Over+1.5&bt=dc|Home+or+Draw"
    html = client.get(q + "&todds=3&maxlegs=4").get_data(as_text=True)
    assert "Highest chance for total odds of 3" in html and "not a guarantee" in html
    best = html.split("Highest chance for total odds of 3")[1].split("Other ways")[0]
    sels = [json.loads(v.replace("&#34;", '"')) for v in re.findall(r"name=\"sel\"[^>]*?value='([^']+)'", best)]
    assert 1 <= len(sels) <= 4 and len({s["eventId"] for s in sels}) == len(sels)
    odds = float(re.search(r'Together, estimated<td class="num">([\d.]+)', best).group(1))
    assert odds >= 2.98
    # ranked by estimated chance, at most 4 selections each
    table = html.split("Other ways")[1].split("The list")[0] if "Other ways" in html else ""
    if table:
        ks = [int(k) for k in re.findall(r'<tr class="[^"]*"><td class="num">(\d+)', table)]
        ps = [float(p) for p in re.findall(r'<td class="num">[\d.]+<td class="num">([\d.]+)%', table)]
        assert all(k <= 4 for k in ks) and ps == sorted(ps, reverse=True)
    r = client.post("/codes/make", data={"sel": [json.dumps(s) for s in sels]})
    assert r.status_code == 200
    html = client.get(q + "&todds=5000&maxlegs=2").get_data(as_text=True)
    assert "No selections inside your filters reach total odds of 5000" in html


def test_other_markets_and_tabs(client, arsenal):
    upload(client, json.dumps(make_league(_games(arsenal, 2))))
    for g in _games(arsenal, 2):                                     # the same games, fetched in full
        upload(client, json.dumps({"bizCode": 10000, "data": g}))
    html = client.get("/leagues/?mode=screen").get_data(as_text=True)
    assert "Other markets" in html and "1H Team Total: Over 0.5" in html
    assert 'value="team_goals|Over 0.5" checked' in html            # the default bet
    html = client.get("/leagues/?mode=screen&sent=1&upcoming=1&bt=other|1X2:+Team").get_data(as_text=True)
    assert len(_rows(html)) == 4
    assert "Choose the bet, find the teams" in client.get("/leagues/?upcoming=1").get_data(as_text=True)


def test_old_saved_picks_are_rebuilt(tmp_path, arsenal):
    import sqlite3
    path = str(tmp_path / "old.db")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE picks(event_id TEXT, family TEXT, label TEXT)")
    con.execute("CREATE TABLE priced_at(event_id TEXT PRIMARY KEY, saved_at INTEGER, banned INTEGER)")
    con.execute("INSERT INTO priced_at VALUES('x', 1, 0)")
    con.commit()
    con.close()
    con = connect(path)
    cols = {r["name"] for r in con.execute("PRAGMA table_info(picks)")}
    assert {"bkey", "prob_ok", "mkt_kept"} <= cols
    assert con.execute("SELECT COUNT(*) FROM priced_at").fetchone()[0] == 0
