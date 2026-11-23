"""Who may talk to the app: only this computer's own pages, and the bookmark from sportybet.com."""
import logging

from test_bridge import SB, _key


def test_dns_rebinding_is_refused(client):
    # a website that points its own name at 127.0.0.1 still sends its own name as the Host
    evil = {"Host": "evil.example:5000", "Origin": "http://evil.example:5000"}
    assert client.get("/", headers={"Host": "evil.example:5000"}).status_code == 400
    assert client.get("/results/", headers={"Host": "evil.example"}).status_code == 400
    assert client.post("/codes/delete", data={"all": "1"}, headers=evil).status_code == 400
    for host in ("127.0.0.1:5000", "localhost:5000", "localhost", "[::1]:5000"):
        assert client.get("/", headers={"Host": host}).status_code == 200


def test_cross_site_posts_are_refused(client):
    assert client.post("/codes/delete", data={"all": "1"}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post("/codes/delete", data={"all": "1"},
                       headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/codes/delete", data={"all": "1"}, headers={"Origin": "null"}).status_code == 403
    ok = {"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"}
    assert client.post("/codes/delete", data={"all": "1"}, headers=ok).status_code == 200


def test_bridge_needs_key_and_sportybet(client):
    k = _key(client)
    assert client.get(f"/bridge/job?v=2&k={k}", headers=SB).status_code == 200
    assert client.get("/bridge/job?v=2&k=wrong", headers=SB).status_code == 403
    assert client.get(f"/bridge/job?v=2&k={k}", headers={"Origin": "https://sportybet.com.evil.example"}).status_code == 403
    # another site can't queue fetches or make codes, even with the key
    bad = {"Origin": "https://evil.example"}
    assert client.post("/bridge/queue", json={"requests": [{"url": "https://www.sportybet.com/x"}]},
                       headers=bad).status_code == 403
    assert client.post("/codes/make", data={"sel": "{}"}, headers=bad).status_code == 403


def test_only_sportybet_addresses_can_be_queued(client):
    r = client.post("/bridge/queue", json={"label": "x", "requests": [{"url": "https://evil.example/steal"}]})
    assert r.status_code == 400


def test_key_is_hidden_in_the_log(app):
    from app import _HideKey
    rec = logging.LogRecord("werkzeug", logging.INFO, "", 0, '%s - - "%s" %s',
                            ("127.0.0.1", "GET /bridge/job?v=2&k=SECRET123 HTTP/1.1", "200"), None)
    _HideKey().filter(rec)
    assert "SECRET123" not in rec.getMessage() and "k=(hidden)" in rec.getMessage()
