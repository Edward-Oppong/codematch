import json

from conftest import future, upload
from test_fixtures_across_codes import multi_code

from app.analysis import codes as review
from app.analysis import markets


def test_two_legs_on_one_game_are_both_kept(client, arsenal):
    g = future(arsenal)
    upload(client, json.dumps(multi_code("SAME1", [(g, "1", "", "Home"), (g, "18", "total=1.5", "Over 1.5")])))
    html = client.get("/").get_data(as_text=True)
    assert "2 <span class=\"muted\">on 1</span>" in html        # 2 legs, 1 game


def _legs(arsenal, picks):
    names = (arsenal["homeTeamName"], arsenal["awayTeamName"])
    out = []
    for mid, spec, desc in picks:
        m = next(m for m in arsenal["markets"] if m["id"] == mid and (m.get("specifier") or "") == spec)
        o = next(o for o in m["outcomes"] if o["desc"] == desc)
        out.append({"event_id": arsenal["eventId"], "market_id": mid, "specifier": spec, "pick": desc,
                    "market": m["desc"], "match": " v ".join(names), "odds": float(o["odds"]),
                    "prob": float(o["probability"]), "league": "x", "sel_key": f"{mid}|{spec}|{desc}"})
    return out


def test_same_game_chance_is_joint_not_multiplied(arsenal):
    priced = {f: markets.build_priced(arsenal, f) for f in markets.FAMILIES}
    pf = lambda eid, fam: priced[fam]
    # Arsenal win + Arsenal or draw: the first implies the second, so the joint chance is Arsenal win's
    u = review.combine_same_game(_legs(arsenal, [("1", "", "Home"), ("10", "", "Home or Draw")]), pf)[0]
    assert u["how"] == "exact" and abs(u["prob"] - 0.69) < 0.005
    # Arsenal win + over 1.5: neither implies the other, but the combo "Home & Over 1.5" is priced
    u = review.combine_same_game(_legs(arsenal, [("1", "", "Home"), ("18", "total=1.5", "Over 1.5")]), pf)[0]
    combo = next(v for k, v in priced["goals"].items() if k.startswith("Combo: Home & Over 1.5"))
    assert u["how"] == "exact" and abs(u["prob"] - combo["prob"]) < 1e-9
    # Arsenal win + Leeds win can't both happen
    u = review.combine_same_game(_legs(arsenal, [("1", "", "Home"), ("1", "", "Away")]), pf)[0]
    assert u["how"] == "contradiction" and u["prob"] == 0


def test_history_keeps_only_changes(app, arsenal):
    from app import store
    from app.db import connect
    con = connect(app.config["DB_PATH"])
    n1 = store.record_history(con, arsenal, ts=1)
    n2 = store.record_history(con, arsenal, ts=2)            # same prices again
    assert n1 > 900 and n2 == 0
    moved = json.loads(json.dumps(arsenal))
    m = next(m for m in moved["markets"] if m["id"] == "1")
    m["outcomes"][0]["odds"] = "1.50"
    assert store.record_history(con, moved, ts=3) == 1
    hist = store.price_history(con, arsenal["eventId"], "1X2: Home")
    assert [h["odds"] for h in hist] == [1.43, 1.5]


def test_old_repeated_history_is_pruned(tmp_path, arsenal):
    path = tmp_path / "old.db"
    from app.db import connect
    con = connect(str(path))
    con.execute("DELETE FROM blobs WHERE key='history_pruned'")
    con.executemany("INSERT INTO history VALUES(?,?,?,?,?,?)",
                    [("e", "goals", "x", 1.5, 0.6, t) for t in range(5)] + [("e", "goals", "x", 1.6, 0.6, 9)])
    con.commit()
    con.close()
    con = connect(str(path))
    assert [r[0] for r in con.execute("SELECT odds FROM history WHERE label='x' ORDER BY ts")] == [1.5, 1.6]


def test_run_refuses_debug_on_public_address(monkeypatch):
    import runpy
    import pytest
    monkeypatch.setenv("CODEMATCH_DEBUG", "1")
    monkeypatch.setenv("CODEMATCH_HOST", "0.0.0.0")
    with pytest.raises(SystemExit):
        runpy.run_path("run.py", run_name="__main__")
