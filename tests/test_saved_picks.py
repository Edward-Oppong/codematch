"""Each game's picks are priced once at import and read back as rows, instead of re-reading the whole game."""
import json

from conftest import future, make_league, upload

from app import store
from app.analysis import markets
from app.db import connect


def _game(arsenal, i=0):
    g = future(arsenal, hours=5 + i)
    g["eventId"], g["homeTeamName"], g["awayTeamName"] = f"sr:match:{300 + i}", f"H{i}", f"A{i}"
    g["sport"]["category"] = {"id": "c", "name": "X", "tournament": {"id": "sr:tournament:17", "name": "PL"}}
    return g


def test_saved_at_import_and_same_as_computed(app, client, arsenal):
    g = _game(arsenal)
    upload(client, json.dumps(make_league([g])))
    con = connect(app.config["DB_PATH"])
    saved = store.load_picks(con, [g["eventId"]], ["goals"])[g["eventId"]]
    fresh = markets.build_priced(g, "goals")
    assert saved.keys() == fresh.keys()
    for k, v in fresh.items():
        assert abs(saved[k]["odds"] - v["odds"]) < 1e-9 and abs(saved[k]["prob"] - v["prob"]) < 1e-9
        assert bool(saved[k]["push"]) == bool(v["push"]) and saved[k]["oid"] == v["oid"]
    # filtered in the database
    some = store.load_picks(con, [g["eventId"]], ["goals"], minp=0.6, maxp=0.8, mino=1.2, maxo=1.5)[g["eventId"]]
    assert some and all(0.6 <= v["prob"] <= 0.8 and 1.2 <= v["odds"] < 1.5 for v in some.values())


def test_reimport_replaces_and_delete_removes(app, client, arsenal):
    g = _game(arsenal)
    upload(client, json.dumps(make_league([g])))
    g2 = json.loads(json.dumps(g))
    m = next(m for m in g2["markets"] if m["id"] == "1")
    o = next(o for o in m["outcomes"] if o["desc"] == "Home")
    o["odds"] = "9.99"
    upload(client, json.dumps({"bizCode": 10000, "data": g2}))
    con = connect(app.config["DB_PATH"])
    assert store.load_picks(con, [g["eventId"]], ["goals"])[g["eventId"]]["1X2: Home"]["odds"] == 9.99
    assert con.execute("SELECT COUNT(*) FROM picks WHERE label='1X2: Home'").fetchone()[0] == 1
    store.delete_event(con, g["eventId"])
    assert con.execute("SELECT COUNT(*) FROM picks").fetchone()[0] == 0


def test_older_database_is_priced_on_first_view(app, client, arsenal):
    upload(client, json.dumps(make_league([_game(arsenal, i) for i in range(3)])))
    con = connect(app.config["DB_PATH"])
    con.execute("DELETE FROM picks")          # as if saved by a version without the picks table
    con.execute("DELETE FROM priced_at")
    con.commit()
    html = client.get("/leagues/?zone=low&fam=goals&upcoming=1").get_data(as_text=True)
    assert "3 have a pick inside your filters" in html
    assert con.execute("SELECT COUNT(*) FROM priced_at").fetchone()[0] == 3
