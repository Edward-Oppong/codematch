"""Tests for Odds Steam & Line Movement."""
import json
from conftest import future, make_league, upload
from app.db import connect
import app.store as store


def test_steam_route_and_store(client, app, arsenal):
    ev = future(arsenal)
    upload(client, json.dumps(make_league([ev])))

    con = connect(app.config["DB_PATH"])
    # Simulate a price change: Arsenal 1X2 opened at 2.20 in history, now currently 1.80 in picks
    con.execute("UPDATE history SET odds=2.20 WHERE event_id=? AND label='1X2: Home'", (ev["eventId"],))
    con.execute("UPDATE picks SET odds=1.80 WHERE event_id=? AND label='1X2: Home'", (ev["eventId"],))
    con.commit()

    # Query store directly
    movers = store.steam_movers(con, [ev["eventId"]], min_pct=5.0, direction="steam")
    assert len(movers) >= 1
    m = next(item for item in movers if item["label"] == "1X2: Home")
    assert m["first_odds"] == 2.20
    assert m["odds"] == 1.80
    assert m["move_pct"] < -10.0

    # Test page
    res = client.get("/games/steam?dir=steam&minpct=5")
    assert res.status_code == 200
    page = res.get_data(as_text=True)
    assert "Odds Steam & Line Movement" in page
    assert "Arsenal v Leeds United" in page
    assert "Steam" in page
