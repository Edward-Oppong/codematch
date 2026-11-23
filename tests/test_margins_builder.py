"""Tests for building target odds codes from the lowest-margin markets."""
import json
import pytest
from tests.conftest import make_league, upload
from tests.test_target_and_filters import _games


def test_margins_page_renders_empty(client):
    rv = client.get("/leagues/margins")
    assert rv.status_code == 200
    page = rv.data.decode()
    assert "Where SportyBet keeps least" in page


def test_margins_page_renders_builder_with_games(client, arsenal):
    upload(client, json.dumps(make_league(_games(arsenal, 4))))
    rv = client.get("/leagues/margins")
    assert rv.status_code == 200
    page = rv.data.decode()
    assert "Build Code from Lowest-Margin Markets" in page
    assert "Target Odds at least" in page


def test_margins_builder_with_goal_param(client, arsenal):
    upload(client, json.dumps(make_league(_games(arsenal, 4))))
    rv = client.get("/leagues/margins?goal=2.5")
    assert rv.status_code == 200
    page = rv.data.decode()
    assert "Build Code from Lowest-Margin Markets" in page
