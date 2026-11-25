import datetime
import json

from conftest import future, make_league, upload


def _setup(client, arsenal):
    ev = future(arsenal, hours=30)
    upload(client, json.dumps(make_league([ev])))
    return ev


def _day(ms):
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).date().isoformat()


def test_every_page_loads_empty(client):
    for url in ("/", "/codes/hub", "/leagues/", "/leagues/parlay", "/leagues/singles",
                "/games/", "/import/", "/results/", "/results/settlement", "/guide",
                "/leagues/fetch?tid=sr:tournament:17", "/leagues/sr:tournament:17", "/code/NOPE"):
        r = client.get(url)
        assert r.status_code in (200, 302), url
    assert client.get("/games/sr:match:9").status_code == 404


def test_leagues_review_by_date_and_zone(client, arsenal):
    ev = _setup(client, arsenal)
    d = _day(ev["estimateStartTime"])
    html = client.get(f"/leagues/?start={d}&end={d}&fam=goals&zone=low&upcoming=1").get_data(as_text=True)
    assert "Arsenal v Leeds United" in html and "Lower risk" in html
    html = client.get(f"/leagues/?start={d}&end={d}&fam=goals&fam=bookings&zone=high&upcoming=1").get_data(as_text=True)
    assert "Higher risk" in html
    other = (datetime.date.fromisoformat(d) + datetime.timedelta(days=5)).isoformat()
    html = client.get(f"/leagues/?start={other}&end={other}&upcoming=1").get_data(as_text=True)
    assert "0 games from" in html


def test_league_and_game_pages(client, arsenal):
    _setup(client, arsenal)
    html = client.get("/leagues/sr:tournament:17").get_data(as_text=True)
    assert "Arsenal v Leeds United" in html and "1.43" in html
    html = client.get("/games/sr:match:72221292?fam=goals&pick=Home Total: Over 1.5").get_data(as_text=True)
    assert "Safer: does at least as well" in html and "Home Total: Over 0.5" in html
    html = client.get("/games/sr:match:72221292?fam=bookings&zone=low").get_data(as_text=True)
    assert "Total Bookings: Over 1.5" in html


def test_directory_feeds_league_picker(client):
    directory = {"bizCode": 10000, "data": {"sportList": [{"categories": [
        {"name": "England", "eventSize": 21, "tournaments": [
            {"id": "sr:tournament:17", "name": "Premier League", "eventSize": 21, "categoryName": "England"}]}]}]}}
    assert "League directory saved (1 leagues)" in upload(client, json.dumps(directory))
    html = client.get("/leagues/").get_data(as_text=True)
    assert 'value="sr:tournament:17"' in html
    html = client.get("/leagues/fetch?tid=sr:tournament:17").get_data(as_text=True)
    assert "England Premier League" in html and "pcEvents" in html


def test_old_match_links_redirect(client):
    r = client.get("/match/sr:match:72221292")
    assert r.status_code == 302 and "/games/sr:match:72221292" in r.headers["Location"]
