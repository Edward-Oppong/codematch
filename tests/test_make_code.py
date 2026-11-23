import json
import re

from conftest import make_league, upload
from test_bridge import SB, _key
from test_target_and_filters import _games


def _ticked(html):
    return re.findall(r'<input type="checkbox" name="sel" aria-label="Use this pick" checked\s+value=\'([^\']+)\'', html)


def test_target_picks_come_pre_ticked(client, arsenal):
    upload(client, json.dumps(make_league(_games(arsenal, 6))))
    html = client.get("/leagues/?zone=low&fam=goals&upcoming=1&target=60").get_data(as_text=True)
    n = int(re.search(r"Picks that fit your 60% target</span><b[^>]*>(\d+) of 6", html).group(1))
    sels = [json.loads(v.replace("&#34;", '"')) for v in _ticked(html)]
    assert len(sels) == n and all(s["eventId"].startswith("sr:match:") and s["outcomeId"] for s in sels)
    assert "Make a SportyBet booking code from the ticked picks" in html


def _make(client, sels):
    return client.post("/codes/make", data={"sel": [json.dumps(s) for s in sels]})


def test_make_code_round_trip(client, arsenal):
    k = _key(client)
    sel = {"eventId": "sr:match:72221292", "marketId": "1", "specifier": "", "outcomeId": "1"}
    job_id = _make(client, [sel]).get_json()["id"]
    j = client.get(f"/bridge/job?v=2&k={k}", headers=SB).get_json()
    req = j["requests"][-1]                                  # the game is fetched again first, to check its odds
    assert "factsCenter/event" in j["requests"][0]["url"] and len(j["requests"]) == 2
    assert req["url"] == "https://www.sportybet.com/api/gh/orders/share"
    assert json.loads(req["body"]) == {"selections": [{**sel, "specifier": None}]}
    # SportyBet answers with the new code
    client.post(f"/bridge/import?job={job_id}&k={k}", headers=SB, content_type="text/plain",
                data=json.dumps({"bizCode": 10000, "data": {"shareCode": "ab12cd", "shareURL": "https://x"}}))
    s = client.post(f"/bridge/done?job={job_id}&k={k}", headers=SB).get_json()
    assert s["summary"] == "Booking code AB12CD made on SportyBet."


def test_make_code_failures_are_explained(client):
    k = _key(client)
    sel = {"eventId": "sr:match:1", "marketId": "1", "specifier": "", "outcomeId": "1"}
    job_id = _make(client, [sel]).get_json()["id"]
    client.get(f"/bridge/job?v=2&k={k}", headers=SB)
    client.post(f"/bridge/import?job={job_id}&k={k}", headers=SB, content_type="text/plain",
                data=json.dumps({"bizCode": 4200, "message": "Selection is no longer available", "data": None}))
    client.post(f"/bridge/import?job={job_id}&refused=404&label=make%20a%20booking%20code&k={k}", headers=SB,
                content_type="text/plain", data="<html>Not found</html>")
    msgs = client.get(f"/bridge/status?job={job_id}").get_json()["msgs"]
    assert [False, "SportyBet said: Selection is no longer available"] in msgs
    assert any("refused \"make a booking code\" (HTTP 404): <html>Not found</html>" in m for ok, m in msgs)


def test_make_code_checks_its_input(client):
    assert _make(client, []).status_code == 400
    assert _make(client, [{"eventId": "https://evil", "marketId": "1", "outcomeId": "1"}]).status_code == 400
    many = lambda n: [{"eventId": f"sr:match:{i}", "marketId": "1", "outcomeId": "1"} for i in range(n)]
    assert _make(client, many(1) * 3).get_json()["codes"] == 1             # repeats count once
    assert _make(client, many(51)).get_json()["codes"] == 2                 # more than SportyBet takes: two codes
    assert _make(client, many(501)).status_code == 400                      # more than ten codes in one go


def test_old_bookmark_is_flagged(client):
    k = _key(client)
    client.get(f"/bridge/job?k={k}", headers=SB)                       # a version-1 button sends no version
    assert "Update needed" in client.get("/import/").get_data(as_text=True)
    client.get(f"/bridge/job?v=3&k={k}", headers=SB)
    assert "Update needed" not in client.get("/import/").get_data(as_text=True)
    client.get(f"/bridge/job?v=2&k={k}", headers=SB)                    # version 2 can't take added requests
    assert "Update needed" in client.get("/import/").get_data(as_text=True)


def test_odds_are_checked_before_the_code_is_made(client, arsenal):
    from conftest import future
    g = future(arsenal)
    upload(client, json.dumps({"bizCode": 10000, "data": g}))
    m1 = next(m for m in g["markets"] if m["id"] == "1")
    home = next(o for o in m1["outcomes"] if o["desc"] == "Home")
    m18 = next(m for m in g["markets"] if m["id"] == "18" and m.get("specifier") == "total=2.5")
    over = next(o for o in m18["outcomes"] if o["desc"] == "Over 2.5")
    sels = [{"eventId": g["eventId"], "marketId": "1", "specifier": "", "outcomeId": home["id"]},
            {"eventId": g["eventId"], "marketId": "18", "specifier": "total=2.5", "outcomeId": over["id"]}]
    k = _key(client)
    job_id = _make(client, sels).get_json()["id"]
    reqs = client.get(f"/bridge/job?v=2&k={k}", headers=SB).get_json()["requests"]
    assert len(reqs) == 2 and "factsCenter/event" in reqs[0]["url"]
    # by the time the button fetches it, Home has drifted and Over 2.5 is suspended
    now = json.loads(json.dumps(g))
    for m in now["markets"]:
        for o in m["outcomes"]:
            if m["id"] == "1" and o["desc"] == "Home":
                o["odds"] = f'{float(o["odds"]) + 0.2:.2f}'
            if m["id"] == "18" and m.get("specifier") == "total=2.5" and o["desc"] == "Over 2.5":
                o["isActive"] = 0
    client.post(f"/bridge/import?job={job_id}&k={k}", headers=SB, content_type="text/plain",
                data=json.dumps({"bizCode": 10000, "data": now}))
    client.post(f"/bridge/import?job={job_id}&k={k}", headers=SB, content_type="text/plain",
                data=json.dumps({"bizCode": 10000, "data": {"shareCode": "zz99yy", "shareURL": "https://x"}}))
    client.post(f"/bridge/done?job={job_id}&k={k}", headers=SB)
    s = client.get(f"/bridge/status?job={job_id}").get_json()
    html = s["check_html"]
    assert "Code ZZ99YY" in html
    assert "1 pick is no longer on offer" in html and "1 pick moved" in html
    assert f'{float(home["odds"]):.2f} → <b>{float(home["odds"]) + 0.2:.2f}</b>' in html


def test_unchecked_when_the_game_fetch_fails(client, arsenal):
    from conftest import future
    g = future(arsenal)
    upload(client, json.dumps({"bizCode": 10000, "data": g}))
    sel = {"eventId": g["eventId"], "marketId": "1", "specifier": "",
           "outcomeId": next(m for m in g["markets"] if m["id"] == "1")["outcomes"][0]["id"]}
    k = _key(client)
    job_id = _make(client, [sel]).get_json()["id"]
    client.get(f"/bridge/job?v=2&k={k}", headers=SB)
    client.post(f"/bridge/import?job={job_id}&k={k}&refused=403&label=x", headers=SB, content_type="text/plain", data="no")
    client.post(f"/bridge/import?job={job_id}&k={k}", headers=SB, content_type="text/plain",
                data=json.dumps({"bizCode": 10000, "data": {"shareCode": "aa11bb", "shareURL": "https://x"}}))
    client.post(f"/bridge/done?job={job_id}&k={k}&failed=1", headers=SB)
    html = client.get(f"/bridge/status?job={job_id}").get_json()["check_html"]
    assert "Code AA11BB" in html and "couldn't be fetched again" in html


def _made_with_answer(client, arsenal, answer=None, refused=None):
    from conftest import future
    g = future(arsenal)
    upload(client, json.dumps({"bizCode": 10000, "data": g}))
    sel = {"eventId": g["eventId"], "marketId": "1", "specifier": "",
           "outcomeId": next(m for m in g["markets"] if m["id"] == "1")["outcomes"][0]["id"]}
    k = _key(client)
    job_id = _make(client, [sel]).get_json()["id"]
    client.get(f"/bridge/job?v=2&k={k}", headers=SB)
    client.post(f"/bridge/import?job={job_id}&k={k}", headers=SB, content_type="text/plain",
                data=json.dumps({"bizCode": 10000, "data": g}))
    if refused:
        client.post(f"/bridge/import?job={job_id}&k={k}&refused={refused}&label=make+a+booking+code+(1+pick)",
                    headers=SB, content_type="text/plain", data=answer)
    else:
        client.post(f"/bridge/import?job={job_id}&k={k}", headers=SB, content_type="text/plain", data=answer)
    client.post(f"/bridge/done?job={job_id}&k={k}&failed={1 if refused else 0}", headers=SB)
    return client.get(f"/bridge/status?job={job_id}").get_json()["check_html"]


def test_sportybet_refusal_is_shown(client, arsenal):
    html = _made_with_answer(client, arsenal, json.dumps(
        {"bizCode": 19000, "message": "Some selections are no longer available", "data": None}))
    assert "didn't make the code" in html and "Some selections are no longer available" in html


def test_http_refusal_is_shown(client, arsenal):
    html = _made_with_answer(client, arsenal, '{"bizCode":4003,"message":"Too many selections"}', refused="400")
    assert "didn't make the code" in html and "HTTP 400" in html and "Too many selections" in html
