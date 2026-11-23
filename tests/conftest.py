import copy
import json
import os
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import create_app  # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures")


@pytest.fixture(scope="session")
def arsenal_text():
    return open(os.path.join(FIX, "arsenal_leeds.json"), encoding="utf-8").read()


@pytest.fixture(scope="session")
def arsenal(arsenal_text):
    return json.loads(arsenal_text, strict=False)["data"]


def future(ev, hours=24):
    """A copy of the game moved into the future, so 'not started' filters keep it."""
    ev = copy.deepcopy(ev)
    ev["estimateStartTime"] = int(time.time() * 1000) + hours * 3600 * 1000
    return ev


def make_league(events, tid="sr:tournament:17", name="Premier League"):
    return {"bizCode": 10000, "data": [{"id": tid, "name": name, "events": events}]}


def make_code(code, ev, legs):
    """A booking-code response with legs [(market id, specifier, outcome id)] on one game."""
    sels, mkts = [], []
    for mid, spec, oid in legs:
        m = next(m for m in ev["markets"] if m["id"] == mid and (m.get("specifier") or "") == spec)
        sels.append({"eventId": ev["eventId"], "marketId": mid, "specifier": spec, "outcomeId": oid})
        mkts.append(m)
    outcome = {k: ev[k] for k in ("eventId", "homeTeamName", "awayTeamName", "estimateStartTime", "sport")}
    outcome["markets"] = mkts
    return {"bizCode": 10000, "data": {"shareCode": code, "ticket": {"selections": sels}, "outcomes": [outcome]}}


@pytest.fixture
def app(tmp_path):
    return create_app({"DB_PATH": str(tmp_path / "test.db"), "TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


def upload(client, text, name="data.json"):
    import io
    r = client.post("/import/", data={"files": (io.BytesIO(text.encode()), name)}, content_type="multipart/form-data")
    assert r.status_code == 200
    return r.get_data(as_text=True)
