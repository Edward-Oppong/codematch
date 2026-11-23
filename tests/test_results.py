import json

from conftest import future, upload
from test_fixtures_across_codes import multi_code

from app.analysis import settle


def finished(ev, half1, half2):
    """The response SportyBet gives for a game after it ends: no markets, scores per half."""
    return {"bizCode": 10000, "data": {**{k: ev[k] for k in ("eventId", "homeTeamName", "awayTeamName",
                                                           "estimateStartTime", "sport")},
                                       "markets": [], "matchStatus": "Ended", "status": 4,
                                       "setScore": f"{half1[0] + half2[0]}:{half1[1] + half2[1]}",
                                       "gameScore": [f"{half1[0]}:{half1[1]}", f"{half2[0]}:{half2[1]}"]}}


def test_leg_settlement_rules(arsenal):
    leg = lambda mid, spec, pick: {"market_id": mid, "specifier": spec, "pick": pick, "match": "Arsenal v Leeds United"}
    r = (1, 0, 1, 1)                                   # half time 1:0, full time 2:1
    assert settle.leg_status(leg("1", "", "Home"), r) == "won"
    assert settle.leg_status(leg("18", "total=2.5", "Over 2.5"), r) == "won"
    assert settle.leg_status(leg("18", "total=3", "Over 3"), r) == "void"          # exactly 3: refund
    assert settle.leg_status(leg("47", "", "Home/Home"), r) == "won"
    assert settle.leg_status(leg("48", "", "Yes"), r) == "lost"                    # second half was 1:1
    assert settle.leg_status(leg("29", "", "No"), r) == "lost"
    assert settle.leg_status(leg("166", "total=9.5", "Over 9.5"), r) == "manual"   # corners need counting
    assert settle.leg_status(leg("1", "", "Home"), None) == "pending"


def test_results_flow(client, arsenal):
    g1, g2 = future(arsenal, hours=-5), future(arsenal, hours=-4)               # both already played
    g2["eventId"], g2["homeTeamName"], g2["awayTeamName"] = "sr:match:2", "Chelsea", "Spurs"
    for g in (g1, g2):
        upload(client, json.dumps({"bizCode": 10000, "data": g}))
    upload(client, json.dumps(multi_code("WIN2", [(g1, "1", "", "Home"), (g2, "18", "total=1.5", "Over 1.5")])))
    upload(client, json.dumps(multi_code("COR1", [(g1, "166", "total=9.5", "Over 9.5")])))
    client.post("/results/limit", data={"limit": "15"})
    client.post("/results/bet", data={"code": "WIN2", "stake": "10"})
    html = client.post("/results/bet", data={"code": "COR1", "stake": "8"}).get_data(as_text=True)
    assert "over your own limit" in html

    html = client.get("/results/").get_data(as_text=True)
    assert "Games waiting for a score" in html and "running" in html

    upload(client, json.dumps(finished(g1, (1, 0), (1, 1))))                    # Arsenal win 2:1
    msg = upload(client, json.dumps(finished(g2, (0, 0), (1, 1))))              # 1:1, two goals
    assert "final score 1:1 saved" in msg
    html = client.get("/results/").get_data(as_text=True)
    odds = round(1.43 * 1.26, 4)
    assert "won" in html and f"{10 * odds:.2f}" in html                        # 10 x (1.43 x 1.26)
    assert "Legs to mark by hand" in html and "Over 9.5" in html               # the corners leg

    client.post("/results/leg", data={"code": "COR1", "sel_key": _key(client, "COR1"), "status": "lost"})
    html = client.get("/results/").get_data(as_text=True)
    assert "Legs to mark by hand" not in html
    assert f"{10 * odds - 18:+.2f}" in html                                     # all-time result: won 18.02 on 18
    assert "Did SportyBet" in html and "Nothing settled yet" not in html


def _key(client, code):
    import sqlite3
    db = client.application.config["DB_PATH"]
    return sqlite3.connect(db).execute("SELECT sel_key FROM selections WHERE code=?", (code,)).fetchone()[0]


def test_bet_record_survives_deleting_the_code(client, arsenal):
    g = future(arsenal, hours=-5)
    upload(client, json.dumps({"bizCode": 10000, "data": g}))
    upload(client, json.dumps(multi_code("KEEP1", [(g, "1", "", "Home")])))
    client.post("/results/bet", data={"code": "KEEP1", "stake": "5"})
    upload(client, json.dumps(finished(g, (0, 1), (0, 0))))                    # Leeds win
    client.get("/results/")                                                    # settles and keeps the payout
    client.post("/import/clear", data={"what": "everything"})
    html = client.get("/results/").get_data(as_text=True)
    assert "KEEP1" in html and "lost" in html and "-5.00" in html
