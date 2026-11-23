"""Tests for the Master Guide page."""
import pytest


def test_guide_page_renders_successfully(client):
    rv = client.get("/guide")
    assert rv.status_code == 200
    page = rv.data.decode()
    assert "Master Guide" in page
    assert "Setting Up the CodeMatch Bookmark Button" in page
    assert "Value Singles" in page
    assert "Kelly Criterion" in page
    assert "Closing Line Value" in page
    assert "Complete Metric Glossary" in page
    assert "Cloud Deployment" in page
