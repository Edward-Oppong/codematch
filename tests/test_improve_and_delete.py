import json
import re

from conftest import future, upload
from test_fixtures_across_codes import multi_code


def _games(arsenal, n):
    out = []
    for i in range(n):
        g = future(arsenal, hours=5 + i)
        g["eventId"], g["homeTeamName"], g["awayTeamName"] = f"sr:match:{700 + i}", f"Home{i}", f"Away{i}"
        out.append(g)
    return out


def _stat(html, name):
    """'Chance of winning' card on the improve section: (before, after) as floats."""
    m = re.search(name + r"</span><b[^>]*>([\d.]+)%? → ([\d.]+)%?</b>", html)
    return float(m.group(1)), float(m.group(2))


def test_raise_the_chance(client, arsenal):
    games = _games(arsenal, 8)
    for g in games:
        upload(client, json.dumps({"bizCode": 10000, "data": g}))
    legs = [(g, "1", "", "Home") for g in games[:4]] + [(g, "18", "total=2.5", "Over 2.5") for g in games[4:]]
    upload(client, json.dumps(multi_code("BIG8", legs)))

    html = client.get("/code/BIG8?swap=1&mino=1.10").get_data(as_text=True)
    before, after = _stat(html, "Chance of winning")
    assert after > before
    assert "Instead of" in html and "8 legs swapped" in html

    html = client.get("/code/BIG8?keep=3").get_data(as_text=True)
    assert "8 → 3" in html
    before, after = _stat(html, "Chance of winning")
    assert after > before * 5                               # dropping 5 legs matters far more than any swap

    # a minimum odds above every safer pick means nothing can be swapped
    html = client.get("/code/BIG8?swap=1&mino=50").get_data(as_text=True)
    assert "0 legs swapped" in html


def test_delete_codes_and_data(client, arsenal):
    games = _games(arsenal, 2)
    for g in games:
        upload(client, json.dumps({"bizCode": 10000, "data": g}))
    for c in ("AAA1", "BBB2", "CCC3"):
        upload(client, json.dumps(multi_code(c, [(games[0], "1", "", "Home")])))

    html = client.post("/codes/delete", data={"code": ["AAA1", "BBB2"]}).get_data(as_text=True)
    assert "Deleted 2 codes" in html and "CCC3" in html and "/code/AAA1" not in html
    html = client.post("/codes/delete", data={"all": "1"}).get_data(as_text=True)
    assert "Deleted 1 code." in html and "No codes saved yet" in html

    html = client.post("/import/clear", data={"what": "old_games"}).get_data(as_text=True)
    assert "Deleted 0 games" in html                        # both games are in the future
    upload(client, json.dumps(multi_code("DDD4", [(games[1], "1", "", "Home")])))
    html = client.post("/import/clear", data={"what": "everything"}).get_data(as_text=True)
    assert "Deleted 1 codes and 2 games" in html
    assert "Saved now: 0 codes, 0 games" in html
