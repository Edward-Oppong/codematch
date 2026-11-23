import json
import re

from conftest import make_league, upload
from test_target_and_filters import _games


def test_margins_page(client, arsenal):
    upload(client, json.dumps(make_league(_games(arsenal, 4))))
    html = client.get("/leagues/margins").get_data(as_text=True)
    assert "Where SportyBet keeps least" in html and "By market" in html and "By league" in html
    kept = [float(x) for x in re.findall(r'data-label="SportyBet keeps" class="num"><b>(-?[\d.]+)%', html)]
    assert len(kept) > 10 and kept == sorted(kept)          # smallest margin first
    assert "1X2" in html
    html = client.get("/leagues/margins?fam=corners").get_data(as_text=True)
    assert "1X2</td>" not in html.split("By league")[0].replace("\n", "")
    assert "Where SportyBet keeps least" in client.get("/leagues/?upcoming=1").get_data(as_text=True)


def test_margins_empty(client):
    html = client.get("/leagues/margins").get_data(as_text=True)
    assert "No saved games" in html
