import json
import re
from urllib.parse import unquote

from conftest import future

SB = {"Origin": "https://www.sportybet.com"}


def _key(client):
    html = client.get("/import/").get_data(as_text=True)
    href = re.search(r'class="bookmark" href="([^"]+)"', html).group(1)
    code = unquote(href.replace("&amp;", "&").replace("&#34;", '"'))
    assert code.startswith("javascript:")
    return re.search(r'K="([^"]+)"', code).group(1)


def test_round_trip(client, arsenal):
    k = _key(client)
    reqs = [{"label": "Arsenal v Leeds", "url": "https://www.sportybet.com/api/gh/factsCenter/event?eventId=1"}]
    r = client.post("/bridge/queue", json={"label": "Arsenal v Leeds", "requests": reqs})
    job_id = r.get_json()["id"]

    r = client.get(f"/bridge/job?v=3&k={k}", headers=SB)
    assert r.get_json()["requests"] == reqs
    assert r.headers["Access-Control-Allow-Origin"] == "https://www.sportybet.com"
    assert r.headers["Access-Control-Allow-Private-Network"] == "true"
    assert client.get(f"/bridge/job?v=3&k={k}", headers=SB).get_json()["requests"] == []   # handed out once

    body = json.dumps({"bizCode": 10000, "data": future(arsenal)})
    assert client.post(f"/bridge/import?job={job_id}&k={k}", data=body, headers=SB,
                       content_type="text/plain").get_json()["ok"]
    assert client.get(f"/bridge/status?job={job_id}").get_json()["status"] == "fetching"
    s = client.post(f"/bridge/done?job={job_id}&failed=0&k={k}", headers=SB).get_json()
    assert s["summary"] == "imported 1 item."
    s = client.get(f"/bridge/status?job={job_id}").get_json()
    assert s["status"] == "done" and "saved 1347 markets" in s["msgs"][0][1]
    assert client.get("/games/sr:match:72221292").status_code == 200
    assert "Working: it has fetched data before" in client.get("/import/").get_data(as_text=True)


def test_match_page_with_nothing_queued(client, arsenal):
    k = _key(client)
    body = json.dumps({"bizCode": 10000, "data": future(arsenal)})
    client.post(f"/bridge/import?job=&k={k}", data=body, headers=SB, content_type="text/plain")
    assert client.post(f"/bridge/done?job=&k={k}", headers=SB).get_json()["summary"] == "imported 1 item."


def test_security(client):
    k = _key(client)
    assert client.get("/bridge/job?k=wrong", headers=SB).status_code == 403
    assert client.get(f"/bridge/job?k={k}").status_code == 403                                    # no origin
    assert client.get(f"/bridge/job?k={k}", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get(f"/bridge/job?k={k}", headers={"Origin": "https://sportybet.com.evil.example"}).status_code == 403
    r = client.get(f"/bridge/job?k={k}", headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in r.headers
    # another website can't queue fetches
    assert client.post("/bridge/queue", json={"requests": [{"label": "x", "url": "https://www.sportybet.com/a"}]},
                       headers={"Origin": "https://evil.example"}).status_code == 403
    # and the queue only ever holds sportybet.com addresses
    assert client.post("/bridge/queue", json={"requests": [{"label": "x", "url": "https://evil.example/"}]}).status_code == 400


def test_preflight(client):
    r = client.options("/bridge/import", headers={**SB, "Access-Control-Request-Method": "POST",
                                                  "Access-Control-Request-Private-Network": "true"})
    assert r.status_code == 200 and r.headers["Access-Control-Allow-Private-Network"] == "true"


def test_every_fetch_box_offers_the_button(client, arsenal):
    for url in ("/import/", "/leagues/sr:tournament:17", "/games/sr:match:1"):
        html = client.get(url).get_data(as_text=True)
        assert "Fetch with the CodeMatch button" in html and "data-cm-job='[" in html, url
