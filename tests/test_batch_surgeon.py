"""Tests for Batch Code Surgeon and multi-code audit engine."""
import json
import pytest
from conftest import future, make_league, upload


def test_batch_surgeon_page_loads(client):
    res = client.get("/codes/batch-surgeon")
    assert res.status_code == 200
    page = res.get_data(as_text=True)
    assert "Batch Code Surgeon" in page
    assert "Codes Audited" in page
    assert "Toxic Legs Cured" in page


def test_batch_surgeon_with_codes(client, arsenal):
    ev = future(arsenal)
    upload(client, json.dumps(make_league([ev])))

    # Fetch codehub or create code
    code_text = open("tests/fixtures/codehub.json", encoding="utf-8").read()
    upload(client, code_text, "codehub.json")

    res = client.get("/codes/batch-surgeon")
    assert res.status_code == 200
    page = res.get_data(as_text=True)
    assert "Batch Code Surgeon" in page
    assert "Toxicity" in page
    assert "Grade" in page


def test_batch_surgeon_single_code(client, arsenal):
    ev = future(arsenal)
    upload(client, json.dumps(make_league([ev])))
    code_text = open("tests/fixtures/codehub.json", encoding="utf-8").read()
    upload(client, code_text, "codehub.json")

    res = client.get("/codes/batch-surgeon?code=D7YYMC")
    assert res.status_code == 200
    page = res.get_data(as_text=True)
    assert "D7YYMC" in page
