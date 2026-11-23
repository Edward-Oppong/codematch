"""The link between the CodeMatch bookmark button on sportybet.com and this app.

1. A page in the app queues what to fetch (POST /bridge/queue, from the app itself).
2. On sportybet.com the user clicks the bookmark button. It reads the queue (GET /bridge/job), fetches each item
   with the user's own SportyBet session, posts each response here (POST /bridge/import) and finishes with
   POST /bridge/done.
3. The app page watches GET /bridge/status and shows what was imported.

Only the bookmark button can use steps 2: every call must carry this app's secret key and come from a
sportybet.com page. Responses go through the same importer as uploaded files.
"""
import hmac
import json
import re
import secrets
import time

from flask import Blueprint, abort, jsonify, request

from .. import store
from ..db import get_db
from ..sources.sportybet import importer

bp = Blueprint("bridge", __name__, url_prefix="/bridge")
SPORTYBET = re.compile(r"^https://([a-z0-9-]+\.)*sportybet\.com$")


def key(con):
    """This app's secret key for the bookmark button, made on first use."""
    k = store.settings(con).get("bridge_key")
    if not k:
        k = secrets.token_urlsafe(18)
        store.save_settings(con, bridge_key=k)
    return k


@bp.after_request
def cors(resp):
    origin = request.headers.get("Origin", "")
    if SPORTYBET.match(origin) or origin in ("null", ""):
        resp.headers["Access-Control-Allow-Origin"] = origin if origin and origin != "null" else "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        req_headers = request.headers.get("Access-Control-Request-Headers", "content-type")
        resp.headers["Access-Control-Allow-Headers"] = req_headers or "content-type"
        resp.headers["Access-Control-Allow-Private-Network"] = "true"     # Chrome's local-network check
        resp.headers["Access-Control-Max-Age"] = "600"
    resp.headers["Vary"] = "Origin"
    return resp


def _from_button(con):
    """The call must come from a sportybet.com page and carry the key."""
    if not SPORTYBET.match(request.headers.get("Origin", "")):
        abort(403)
    if not hmac.compare_digest(request.args.get("k", ""), key(con)):
        abort(403)


def _from_app():
    """Calls that change the queue must come from this app's own pages."""
    origin = request.headers.get("Origin")
    if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
        abort(403)


def _job(con):
    r = store.get_blob(con, "bridge_job")
    return r[0] if r else None


def _save(con, job):
    store.put_blob(con, "bridge_job", "meta", job)


MAX_FOLLOW = 60      # games fetched after a Code Hub list, at most (1.5 s each)


def make_job(con, label, requests_, check=None, follow=None):
    """Queue a fetch for the bookmark button. Only sportybet.com addresses are ever queued. Returns the job, or
    None when there's nothing to fetch. check: the picks of a code being made, with the odds they had when it was
    built, to compare with the odds fetched just before making it."""
    reqs = [r for r in requests_ or [] if isinstance(r, dict) and str(r.get("url", "")).startswith(
        "https://www.sportybet.com/")]
    if not reqs:
        return None
    job = {"id": secrets.token_hex(6), "label": str(label or "")[:120], "requests": reqs,
           "created": int(time.time()), "status": "waiting", "received": 0, "failed": 0, "msgs": []}
    if check:
        job["check"] = check
    if follow:
        job["follow"] = follow
    _save(con, job)
    return job


def _follow_hub(con, j, text):
    """After a Code Hub list arrives, the games in its codes that aren't fully imported yet and haven't started,
    as more requests for the button to run in the same trip."""
    from ..sources.sportybet import snippets
    from ..sources.sportybet.parse import classify, parse_hub
    from . import now_ms
    try:
        obj = json.loads(text, strict=False)
    except ValueError:
        return []
    if classify(obj) != "hub":
        return []
    queued = set(j.setdefault("followed", []))
    games = {}
    for c in parse_hub(obj)[0]:
        for l in c["sels"]:
            if (l["start_ms"] or 0) > now_ms() and l["event_id"] not in queued:
                games.setdefault(l["event_id"], l["match"])
    if not games:
        return []
    full = {r["event_id"] for r in con.execute(
        f"SELECT event_id FROM events WHERE n_markets >= 100 AND event_id IN ({','.join('?' * len(games))})",
        list(games))}
    room = MAX_FOLLOW - len(queued)
    todo = [(e, m) for e, m in games.items() if e not in full][:max(0, room)]
    if not todo:
        return []
    add = snippets.events_snippet(todo).requests
    j["followed"] = list(queued | {e for e, _ in todo})
    j["requests"] += add
    return add


@bp.post("/queue")
def queue():
    _from_app()
    body = request.get_json(silent=True) or {}
    job = make_job(get_db(), body.get("label"), body.get("requests"))
    if not job:
        return jsonify(error="nothing to fetch"), 400
    return jsonify(id=job["id"], n=len(job["requests"]))


@bp.get("/job")
def job():
    con = get_db()
    _from_button(con)
    from ..sources.sportybet.snippets import BUTTON_VERSION
    outdated = request.args.get("v") != BUTTON_VERSION
    if outdated != bool(store.settings(con).get("button_outdated")):
        store.save_settings(con, button_outdated=outdated)
    j = _job(con)
    if not j or j["status"] != "waiting" or time.time() - j["created"] > 3600:
        return jsonify(requests=[], message="nothing queued. In CodeMatch, press a \"Fetch with the CodeMatch "
                                            "button\" button first, or open a match page here and click again.")
    j["status"] = "fetching"
    _save(con, j)
    return jsonify(id=j["id"], requests=j["requests"])


def _current_or_adhoc(con, job_id):
    j = _job(con)
    if j and job_id and j["id"] == job_id:
        return j
    if j and j["id"] == "adhoc" and j["status"] == "fetching":
        return j
    # the button fetched the match page it was clicked on, with nothing queued
    j = {"id": "adhoc", "label": "a match page", "requests": [], "created": int(time.time()), "status": "fetching",
         "received": 0, "failed": 0, "msgs": []}
    _save(con, j)
    return j


def _made_or_why(j, text, msgs):
    """In a make-a-code trip: note which games arrived (for the odds check), and recognise SportyBet's answer to
    the make request, whether it holds just the new code or the whole code with its picks. Anything else it answers
    is kept (the start of it), so the page can show what SportyBet said."""
    try:
        obj = json.loads(text, strict=False)
    except ValueError:
        obj = None
    data = obj.get("data") if isinstance(obj, dict) else None
    if isinstance(data, dict) and data.get("eventId"):
        j.setdefault("fetched", []).append(data["eventId"])
        return []
    code = (data.get("shareCode") or data.get("code")) if isinstance(data, dict) else None
    if isinstance(obj, dict) and obj.get("bizCode") in (None, 10000) and isinstance(code, str) and code.strip():
        code = code.strip().upper()
        if any(ok and m.startswith(f"Booking code {code} made") for ok, m in j["msgs"] + [list(x) for x in msgs]):
            return []
        return [(True, f"Booking code {code} made on SportyBet. It's saved on Codes too.")]
    if any(not ok for ok, _ in msgs):
        return []                            # the importer already said what went wrong
    answer = " ".join(text.split())[:300]
    return [(False, f"SportyBet's answer wasn't a booking code: {answer}" if answer else
                    "SportyBet answered with nothing.")]


@bp.post("/import")
def import_one():
    con = get_db()
    _from_button(con)
    j = _current_or_adhoc(con, request.args.get("job"))
    refused = request.args.get("refused")
    if refused:
        # SportyBet refused this request; keep its status and the start of its answer, so it can be fixed
        answer = " ".join(request.get_data(as_text=True).split())[:200]
        j["msgs"].append([False, f"SportyBet refused \"{request.args.get('label', '')[:80]}\" (HTTP {refused[:3]})"
                                 + (f": {answer}" if answer else ".")])
        _save(con, j)
        return jsonify(ok=False)
    text = request.get_data(as_text=True)
    msgs = importer.import_text(con, text)
    if j.get("check"):
        generic = "isn't a response type the app uses"
        extra = _made_or_why(j, text, [m for m in msgs if generic not in m[1]])
        if extra:                            # SportyBet's own answer says more than "not a response type"
            msgs = [m for m in msgs if generic not in m[1]] + extra
    add = _follow_hub(con, j, text) if j.get("follow") == "hub_games" else []
    if add:
        j["msgs"].append([True, f"Fetching the {len(add)} games in these codes too, for their full odds"])
    j["received"] += 1
    j["msgs"] += [list(m) for m in msgs]
    _save(con, j)
    return jsonify(ok=all(ok for ok, _ in msgs), add=add)


@bp.post("/done")
def done():
    con = get_db()
    _from_button(con)
    j = _current_or_adhoc(con, request.args.get("job"))
    try:
        j["failed"] = int(request.args.get("failed") or 0)
    except ValueError:
        pass
    j["status"] = "done"
    j["finished"] = int(time.time())
    _save(con, j)
    store.save_settings(con, bridge_used=True)
    return jsonify(summary=summary(j))


def made_codes(j):
    """The booking codes SportyBet made in this trip, in the order it made them."""
    out = []
    for ok, m in j["msgs"]:
        if ok and m.startswith("Booking code ") and " made on SportyBet" in m:
            code = m.split()[2]
            if code not in out:
                out.append(code)
    return out


def summary(j):
    made = made_codes(j)
    if len(made) == 1:
        return f"Booking code {made[0]} made on SportyBet."
    if made:
        asked = j.get("n_make") or len(made)
        return (f"Booking codes {', '.join(made)} made on SportyBet" +
                (f" ({len(made)} of the {asked} asked for)." if len(made) < asked else "."))
    good = [m for ok, m in j["msgs"] if ok]
    bad = [m for ok, m in j["msgs"] if not ok]
    out = f"imported {len(good)} item{'s' if len(good) != 1 else ''}"
    if bad:
        out += f", {len(bad)} couldn't be read"
    return out + "."


@bp.get("/status")
def status():
    _from_app()
    j = _job(get_db())
    if not j or (request.args.get("job") and j["id"] != request.args.get("job")):
        return jsonify(status="unknown")
    out = dict(status=j["status"], received=j["received"], total=len(j["requests"]), failed=j.get("failed", 0),
               msgs=j["msgs"][-40:], summary=summary(j))
    if j["status"] == "done" and j.get("check"):
        from flask import render_template
        out["check_html"] = render_template("_odds_check.html", c=odds_check(get_db(), j))
    return jsonify(**out)


@bp.post("/clear-job")
def clear_job():
    """Clear a stuck or stale queued job so the next fetch starts fresh."""
    _from_app()
    con = get_db()
    j = _job(con)
    if j and j["status"] in ("waiting", "fetching"):
        j["status"] = "cancelled"
        _save(con, j)
        return jsonify(ok=True, msg="Stale job cleared. Try fetching again.")
    return jsonify(ok=True, msg="No stale job to clear.")


def odds_check(con, j):
    """The picks of a code just made: odds and chance when it was built, and now, after the games were fetched again
    in the same trip. A pick missing now is suspended or no longer offered."""
    import math
    rows = j["check"]
    now = store.find_picks(con, [r["sel"] for r in rows])
    fetched = set(j.get("fetched", []))
    out = []
    for r, n in zip(rows, now):
        checked = r["sel"]["eventId"] in fetched
        if not checked:
            state = "unchecked"
        elif n is None:
            state = "gone"
        elif r["odds"] is None:
            state = "new"
        elif abs(n["odds"] - r["odds"]) < 0.005:
            state = "same"
        else:
            state = "up" if n["odds"] > r["odds"] else "down"
        out.append({"part": r.get("part"), "match": r["match"], "label": (n or {}).get("label") or r["label"] or "a pick not saved here",
                    "odds_then": r["odds"], "prob_then": r["prob"], "odds_now": n["odds"] if n else None,
                    "prob_now": n["prob"] if n else None, "state": state})
    total = lambda key: math.prod(x[key] for x in out) if all(x[key] is not None for x in out) and out else None
    count = lambda st: sum(1 for x in out if x["state"] == st)
    made = made_codes(j)
    problems = [m for ok, m in j["msgs"] if not ok][-5:]
    return {"problems": problems, "failed": j.get("failed", 0), "n_requests": len(j["requests"]),
            "rows": out, "odds_then": total("odds_then"), "odds_now": total("odds_now"),
            "prob_then": total("prob_then"), "prob_now": total("prob_now"),
            "moved": count("up") + count("down"), "gone": count("gone"), "unchecked": count("unchecked"),
            "code": made[-1] if made else None, "codes": made, "n_make": j.get("n_make") or 1,
            "parts": len({r.get("part") for r in rows}) > 1}