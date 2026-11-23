"""Import SportyBet responses the user downloaded or copied from their own browser.

Accepts one or several responses in one paste or file (the console snippets save several, one per line),
and HAR exports. Only the JSON responses are kept: anything around them (URLs, headers, cookies pasted by
mistake) is skipped without being read or stored, and in a HAR only the response bodies are looked at.
"""
import base64
import json
from collections import Counter

from ... import store
from ...analysis import markets
from .parse import ParseError, classify, final_score, parse_code, parse_hub


def extract_all_json(text):
    """Every JSON object/array found in the text, in order. Text between them is ignored."""
    dec = json.JSONDecoder(strict=False)  # SportyBet text fields contain raw control characters
    out, i, n = [], 0, len(text)
    while i < n:
        if text[i] in "{[":
            try:
                obj, end = dec.raw_decode(text, i)
                out.append(obj)
                i = end
                continue
            except ValueError:
                pass
        i += 1
    return out


def is_har(obj):
    return isinstance(obj, dict) and isinstance(obj.get("log"), dict) and isinstance(obj["log"].get("entries"), list)


def _har_bodies(obj):
    """Response bodies only. Request URLs, headers and cookies in the file are never looked at."""
    for ent in obj["log"]["entries"]:
        c = (ent.get("response") or {}).get("content") or {}
        text = c.get("text")
        if not text:
            continue
        if c.get("encoding") == "base64":
            try:
                text = base64.b64decode(text).decode("utf-8", errors="replace")
            except ValueError:
                continue
        yield text


def _handle(con, obj):
    """Import one parsed response. Returns (kind, [(ok, message), ...])."""
    kind = classify(obj)
    msgs = []
    try:
        if kind == "code" and not (obj["data"].get("ticket") and obj["data"].get("outcomes")):
            code = obj["data"]["shareCode"].upper()
            store.put_blob(con, "last_made_code", "meta", {"code": code})
            msgs.append((True, f"Booking code {code} made on SportyBet. Fetch it on Codes to review it."))
        elif kind == "code":
            code = obj["data"]["shareCode"].upper()
            sels = parse_code(obj)
            store.save_code(con, code, sels)
            msgs.append((True, f"Booking code {code}: saved {len(sels)} selections"))
        elif kind == "hub":
            names = store.league_names(con)
            have = {c["code"] for c in store.codes(con)}
            got, skipped = parse_hub(obj, lambda tid: names.get(tid) or tid or "league not known")
            for c in got:
                store.save_code(con, c["code"], c["sels"], source="hub", popularity=c["popularity"], commit=False)
            con.commit()
            new = sum(1 for c in got if c["code"] not in have)
            msgs.append((True, f"Code Hub: saved {len(got)} codes ({new} new)" + (
                f"; left out {skipped} that aren't accumulators (system or other bet types)" if skipped else "")))
        elif kind == "event":
            ev = obj["data"]
            score = final_score(ev)
            if score:
                store.save_result(con, ev["eventId"], *score)
                msgs.append((True, f'{ev.get("homeTeamName")} v {ev.get("awayTeamName")}: final score '
                                   f'{score[0] + score[2]}:{score[1] + score[3]} saved (half time {score[0]}:{score[1]})'))
            if ev.get("markets") or not score:
                msgs.append((True, store.save_event(con, ev)))
        elif kind == "league":
            for lg in obj["data"]:                      # one response can hold several leagues
                if not isinstance(lg, dict) or "events" not in lg:
                    continue
                evs = lg.get("events") or []
                league = {"id": lg["id"], "name": lg.get("name", lg["id"]), "category": lg.get("categoryName")}
                store.put_blob(con, f"league:{lg['id']}", "league", {**league, "eventIds": [e["eventId"] for e in evs]},
                               n=len(evs), name=league["name"])
                fams = [markets.families_present(e) for e in evs]
                for e in evs:
                    store.save_event(con, e, league=league, commit=False)
                con.commit()
                nb, nc = sum(f["bookings"] for f in fams), sum(f["corners"] for f in fams)
                extra = (f" ({nb} with bookings, {nc} with corners)" if nb or nc else
                         " with their main odds only (no bookings or corners in this response)")
                msgs.append((True, f"League {league['name']}: saved {len(evs)} games{extra}"))
        elif kind == "directory":
            ids = lambda d: {t["id"] for c in d["data"]["sportList"][0]["categories"] for t in c.get("tournaments", [])}
            old, _ = store.directory(con)
            now = ids(obj)
            store.put_blob(con, "directory", "directory", obj, name="League directory")
            n = len(now)
            if old:
                try:
                    added = sorted(now - ids(old))
                except (KeyError, IndexError, TypeError):
                    added = []
                store.put_blob(con, "directory_new", "meta", added, n=len(added))
                msgs.append((True, f"League list refreshed: {n} leagues" + (
                    f", {len(added)} new since the last refresh" if added else ", none new since the last refresh")))
            else:
                msgs.append((True, f"League directory saved ({n} leagues)"))
        elif kind == "banned":
            store.put_blob(con, "banned", "banned", obj["data"], n=len(obj["data"]), name="Blocked matches")
            msgs.append((True, f"Blocked-match list saved ({len(obj['data'])} ids); those games will be hidden"))
    except (KeyError, ValueError, TypeError, IndexError) as e:
        why = str(e) if isinstance(e, ParseError) else f"{type(e).__name__}: {e}"
        msgs.append((False, f"Could not read a {kind or 'unknown'} response: {why}"))
    return kind, msgs


def _import_har(con, obj):
    kinds, bad, scanned = Counter(), [], 0
    for text in _har_bodies(obj):
        scanned += 1
        if text.lstrip()[:1] not in ("{", "["):
            continue
        for doc in extract_all_json(text):
            kind, msgs = _handle(con, doc)
            if kind:
                kinds[kind] += sum(1 for ok, _ in msgs if ok)
            bad += [m for ok, m in msgs if not ok]
    names = {"event": "games", "league": "leagues", "code": "booking codes", "hub": "Code Hub lists", "directory": "league directories",
             "banned": "blocked lists"}
    got = ", ".join(f"{n} {names[k]}" for k, n in kinds.items() if n)
    out = [(True, f"HAR file: read {scanned} responses and imported {got}.")] if got else \
          [(False, f"HAR file: read {scanned} responses but none were game, league or booking-code data.")]
    return out + [(False, m) for m in bad[:5]]


def import_text(con, text):
    """Returns a list of (ok, message)."""
    docs = extract_all_json(text)
    if not docs:
        return [(False, "No JSON found. The file or paste should contain a SportyBet response (it starts with { or [).")]
    msgs = []
    for obj in docs:
        if is_har(obj):
            msgs += _import_har(con, obj)
            continue
        kind, m = _handle(con, obj)
        if not m and isinstance(obj, dict) and obj.get("bizCode") not in (None, 10000):
            m = [(False, f"SportyBet said: {obj.get('message') or 'error ' + str(obj.get('bizCode'))}")]
        msgs += m or [(False, "A JSON block was found but it isn't a response type the app uses "
                              "(booking code, Code Hub list, game, league, league directory).")]
    store.name_leagues(con)
    return msgs
