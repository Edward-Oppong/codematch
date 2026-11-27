"""Tests for the Rollover Tracker (store helpers and routes)."""
from app import store
from app.db import get_db


def test_rollover_ladder_math():
    ladder = store.rollover_ladder(5.0, 2.0, 40.0)
    assert len(ladder) == 3
    assert ladder[0] == {"step": 1, "stake": 5.0, "payout": 10.0}
    assert ladder[1] == {"step": 2, "stake": 10.0, "payout": 20.0}
    assert ladder[2] == {"step": 3, "stake": 20.0, "payout": 40.0}


def test_rollover_lifecycle_win_to_target(app):
    with app.app_context():
        con = get_db()
        rid = store.create_rollover(con, "Road to 20", 5.0, 2.0, 20.0)
        rv = store.get_rollover(con, rid)
        assert rv["status"] == "active"
        assert rv["current_stake"] == 5.0

        s1 = store.record_rollover_step(con, rid, 2.0, "won", "Arsenal 1")
        assert s1["payout"] == 10.0
        rv = store.get_rollover(con, rid)
        assert rv["current_step"] == 1
        assert rv["current_stake"] == 10.0
        assert rv["status"] == "active"

        s2 = store.record_rollover_step(con, rid, 2.0, "won", "Barca 1")
        assert s2["payout"] == 20.0
        rv = store.get_rollover(con, rid)
        assert rv["current_step"] == 2
        assert rv["status"] == "won"

        # Further steps cannot be recorded once won
        assert store.record_rollover_step(con, rid, 1.5, "won") is None


def test_rollover_bust_and_restart(app):
    with app.app_context():
        con = get_db()
        rid = store.create_rollover(con, "Test Bust", 5.0, 1.7, 100.0)
        store.record_rollover_step(con, rid, 1.7, "won")
        store.record_rollover_step(con, rid, 1.7, "lost", "Late equalizer")
        rv = store.get_rollover(con, rid)
        assert rv["status"] == "bust"
        assert rv["current_stake"] == 5.0

        store.restart_rollover(con, rid)
        rv = store.get_rollover(con, rid)
        assert rv["status"] == "active"
        assert rv["current_step"] == 0
        assert rv["current_stake"] == 5.0


def test_rollover_routes(client):
    r = client.get("/rollover/")
    assert r.status_code == 200
    assert b"Rollover Tracker" in r.data

    r = client.post("/rollover/new", data={
        "name": "5 GHS Grind",
        "start_stake": "5",
        "target_odds": "1.60",
        "target_amount": "50",
    }, follow_redirects=True)
    assert r.status_code == 200
    assert b"5 GHS Grind" in r.data
    assert b"GHS 5.00" in r.data

    # Extract rollover id from list or test id=1
    r = client.post("/rollover/1/step", data={
        "odds": "1.60",
        "result": "won",
        "note": "Test win",
    }, follow_redirects=True)
    assert r.status_code == 200
    assert b"GHS 8.00" in r.data
    assert b"Test win" in r.data

    r = client.post("/rollover/1/step", data={
        "odds": "1.60",
        "result": "lost",
    }, follow_redirects=True)
    assert r.status_code == 200
    assert b"Bust on step 2" in r.data

    r = client.post("/rollover/1/restart", follow_redirects=True)
    assert r.status_code == 200
    assert b"Record Step 1" in r.data

    r = client.post("/rollover/1/delete", follow_redirects=True)
    assert r.status_code == 200
    assert b"No rollovers yet" in r.data
