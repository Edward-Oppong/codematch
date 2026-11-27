"""Rollover Tracker — a rolling bankroll ladder to grow a small stake step by step."""
from flask import Blueprint, redirect, render_template, request, url_for

from . import now_ms
from .. import store
from ..db import get_db

bp = Blueprint("rollover", __name__, url_prefix="/rollover")


def _money(v, default=None):
    try:
        x = float(str(v).replace(",", "").strip())
        return x if x > 0 else default
    except (ValueError, TypeError):
        return default


@bp.get("/")
def index():
    con = get_db()
    rollovers = store.list_rollovers(con)
    # attach steps to each rollover for display
    for rv in rollovers:
        rv["steps"] = store.rollover_steps(con, rv["id"])
        rv["ladder"] = store.rollover_ladder(rv["start_stake"], rv["target_odds"], rv["target_amount"])
    return render_template("rollover/index.html", rollovers=rollovers)


@bp.get("/<int:rollover_id>")
def detail(rollover_id):
    con = get_db()
    rv = store.get_rollover(con, rollover_id)
    if not rv:
        return redirect(url_for("rollover.index"))
    steps = store.rollover_steps(con, rollover_id)
    ladder = store.rollover_ladder(rv["current_stake"], rv["target_odds"], rv["target_amount"])
    full_ladder = store.rollover_ladder(rv["start_stake"], rv["target_odds"], rv["target_amount"])
    completed = len([s for s in steps if s["result"] == "won"])
    total_staked = sum(s["stake"] for s in steps)
    total_returned = sum(s["payout"] for s in steps)
    net = round(total_returned - total_staked, 2)
    return render_template(
        "rollover/detail.html", rv=rv, steps=steps, ladder=ladder,
        full_ladder=full_ladder, completed=completed,
        total_staked=total_staked, total_returned=total_returned, net=net)


@bp.post("/new")
def new():
    con = get_db()
    name = (request.form.get("name") or "My Rollover").strip()[:60]
    start_stake = _money(request.form.get("start_stake"), 5.0)
    target_odds = _money(request.form.get("target_odds"), 1.70)
    target_amount = _money(request.form.get("target_amount"))
    rid = store.create_rollover(con, name, start_stake, target_odds, target_amount)
    return redirect(url_for("rollover.detail", rollover_id=rid))


@bp.post("/<int:rollover_id>/step")
def add_step(rollover_id):
    con = get_db()
    odds = _money(request.form.get("odds"), 1.70)
    result = request.form.get("result", "won")
    if result not in ("won", "lost"):
        result = "won"
    note = (request.form.get("note") or "").strip()[:120]
    store.record_rollover_step(con, rollover_id, odds, result, note)
    return redirect(url_for("rollover.detail", rollover_id=rollover_id))


@bp.post("/<int:rollover_id>/restart")
def restart(rollover_id):
    store.restart_rollover(get_db(), rollover_id)
    return redirect(url_for("rollover.detail", rollover_id=rollover_id))


@bp.post("/<int:rollover_id>/delete")
def delete(rollover_id):
    store.delete_rollover(get_db(), rollover_id)
    return redirect(url_for("rollover.index"))
