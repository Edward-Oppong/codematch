"""Tests for Value Singles Scanner."""
import json
from conftest import future, make_league, upload
from app.db import get_db
from app import store


def test_value_singles_store_and_page(client, arsenal):
    ev = future(arsenal)
    upload(client, json.dumps(make_league([ev])))

    # Test the page
    res = client.get("/leagues/singles")
    assert res.status_code == 200
    page = res.get_data(as_text=True)
    assert "Value Singles Scanner" in page
    assert "Arsenal v Leeds United" in page
    assert "House Margin" in page
    assert "Kelly Stake" in page
    assert "Back per 1" in page
    assert "Focus Market" in page
    assert "Handicap" in page
    assert "Corners" in page
    assert "Bookings" in page


def test_value_singles_family_filtering(client, app, arsenal):
    ev = future(arsenal)
    upload(client, json.dumps(make_league([ev])))

    # Test filtering via query param
    for fam in ["handicap", "corners", "bookings", "halves", "gg", "dc"]:
        res = client.get(f"/leagues/singles?fam={fam}")
        assert res.status_code == 200
        page = res.get_data(as_text=True)
        assert "Value Singles Scanner" in page

    # Direct store call test with family filtering
    with app.app_context():
        con = get_db()
        ev_id = ev["eventId"]
        all_singles = store.value_singles(con, [ev_id], min_ret=0.50, limit=50)
        assert len(all_singles) > 0

        handicap_singles = store.value_singles(con, [ev_id], family="handicap", min_ret=0.50)
        for s in handicap_singles:
            assert "Handicap" in s["label"] or "Asian" in s["label"]

        corners_singles = store.value_singles(con, [ev_id], family="corners", min_ret=0.50)
        for s in corners_singles:
            assert s["family"] == "corners"

