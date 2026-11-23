"""Early-payout picks (1X2 - 2UP / 1UP): surely won when the team wins, possibly won when it scored enough."""
import json

from conftest import future, make_league, upload

from app.analysis import markets, settle
from app.analysis.markets import leg_info, relation

N = ("Arsenal", "Leeds")


def test_bounds():
    up2 = leg_info("60100", "", "Home", N)
    plain = leg_info("1", "", "Home", N)
    assert up2["early"] == 2 and up2["win"] == plain["win"] and up2["maybe"]
    # 2UP Home surely does at least as well as 1X2 Home; the reverse isn't true
    assert relation(up2, plain) == "a_covers_b"
    # 2UP Home and 1X2 Away can both win (2:0 up, then 2:3), so they don't contradict
    assert relation(up2, leg_info("1", "", "Away", N)) == "overlap"
    # ...but 2UP Home and a 0:1 correct score can't both win
    assert relation(up2, leg_info("45", "", "0:1", N)) == "conflict"
    # double chance home or draw doesn't cover it (2UP may win on 2:3)
    assert relation(leg_info("10", "", "Home or Draw", N), up2) != "a_covers_b"
    assert leg_info("60200", "", "Away", N)["early"] == 1


def leg(pick="Home", mid="60100"):
    return {"market_id": mid, "specifier": "", "pick": pick, "match": "Arsenal v Leeds"}


def test_settle():
    s = lambda r, p="Home", mid="60100": settle.leg_status(leg(p, mid), r)
    assert s((1, 0, 1, 1)) == "won"            # 2:1
    assert s((0, 1, 1, 1)) == "lost"           # 1:2, home never had 2 goals
    assert s((2, 0, 0, 3)) == "manual"         # 2:3, maybe 2 up first
    assert s((1, 1, 0, 0), "Draw") == "won"
    assert s((0, 0, 1, 2), "Home", "60200") == "manual"   # 1UP: 1:2 could have led 1:0
    assert s(None) == "pending"


def test_review_compares_early_leg(client, app, arsenal):
    ev = future(arsenal)
    upload(client, json.dumps({"bizCode": 10000, "data": ev}))
    from app import store
    from app.db import connect
    con = connect(app.config["DB_PATH"])
    store.save_code(con, "EARLY1", [{
        "sel_key": f'{ev["eventId"]}|60100||1', "event_id": ev["eventId"],
        "match": f'{ev["homeTeamName"]} v {ev["awayTeamName"]}', "league": "England Premier League",
        "market": "1X2 - 2UP", "pick": "Home", "odds": 1.5, "start_ms": ev["estimateStartTime"],
        "market_id": "60100", "specifier": "", "outcome_id": "1", "prob": 0.66, "pick_type": "1X2 - 2UP: Home"}])
    page = client.get("/code/EARLY1").get_data(as_text=True)
    assert "early payout" in page and "market not modelled" not in page
    assert "Home or Over 2.5: Yes" in page          # covers every result 2UP Home can pay on
