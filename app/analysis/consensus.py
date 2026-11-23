"""Fixtures that appear in several booking codes: what each code picked on them, and which pick is safest.

For every game in two or more codes:
  - every pick chosen on it, how many codes chose it, and the odds each code had
  - how the picks relate (agree, overlap, or contradict each other)
  - the safest pick any code chose (highest chance of winning)
  - the common-ground pick: the best-priced pick in the whole market that does at least as well as every pick
    the codes chose in that family (needs the game's odds imported)
"""
from collections import defaultdict
from statistics import mean

from . import markets
from .codes import leg_info
from .picks import zone


def _sel(leg):
    """What SportyBet needs to put this pick in a new booking code, or None for legs saved without it."""
    if not (leg.get("market_id") and leg.get("outcome_id") and str(leg.get("event_id", "")).startswith("sr:match:")):
        return None
    return {"eventId": leg["event_id"], "marketId": leg["market_id"], "specifier": leg.get("specifier") or "",
            "outcomeId": leg["outcome_id"]}


def _key(info, leg):
    # picks that win and refund on exactly the same results are the same bet, whatever the market is called
    return (info["family"], info["win"], info["push"], info.get("maybe", 0)) if info else ("?", leg["sel_key"])


def fixtures(legs_by_code, get_event, min_codes=2):
    by_game = defaultdict(list)
    for code, legs in legs_by_code.items():
        for l in legs:
            by_game[l["event_id"]].append((code, l))
    out = []
    for eid, items in by_game.items():
        codes = {c for c, _ in items}
        if len(codes) < min_codes:
            continue
        out.append(_fixture(eid, items, codes, get_event))
    out.sort(key=lambda f: (-f["n_codes"], not f["agree"], -(f["safest"]["prob"] or 0) if f["safest"] else 0))
    return out


def _fixture(eid, items, codes, get_event):
    first = items[0][1]
    ev = get_event(eid)
    priced = {}                                   # family -> priced picks, only when the game is imported
    groups = {}
    for code, l in items:
        info = leg_info(l)
        k = _key(info, l)
        g = groups.setdefault(k, {"labels": set(), "codes": set(), "odds": [], "probs": [], "info": info,
                                  "family": info["family"] if info else None, "sel": _sel(l)})
        g["labels"].add(f'{l["market"]}: {l["pick"]}')
        g["codes"].add(code)
        g["odds"].append(l["odds"])
        if l.get("prob") is not None:
            g["probs"].append(l["prob"])
    picks = []
    for g in groups.values():
        fam, info = g["family"], g["info"]
        live = None
        if ev is not None and fam and not info.get("maybe"):
            if fam not in priced:
                priced[fam] = markets.build_priced(ev, fam)
            live = next((v for v in priced[fam].values()
                         if v["win"] == info["win"] and v["push"] == info["push"]), None)
        prob = live["prob"] if live and not live.get("cond") else (mean(g["probs"]) if g["probs"] else None)
        ret = live["ret"] if live and not live.get("cond") else (mean(g["odds"]) * prob if prob else None)
        picks.append({"label": sorted(g["labels"])[0], "aliases": sorted(g["labels"])[1:], "codes": sorted(g["codes"]),
                      "n": len(g["codes"]), "odds_min": min(g["odds"]), "odds_max": max(g["odds"]),
                      "prob": prob, "ret": ret, "family": fam, "info": info, "refund": bool(info and info["push"]),
                      "from_game": bool(live), "zone": zone(mean(g["odds"])),
                      "live_odds": live["odds"] if live and not live.get("cond") else None, "sel": g["sel"]})
    picks.sort(key=lambda p: (-p["n"], -(p["prob"] or 0)))

    # how the chosen picks relate to each other
    infos = [p["info"] for p in picks if p["info"]]
    conflicts = [(a, b) for i, a in enumerate(picks) for b in picks[i + 1:]
                 if a["info"] and b["info"] and markets.relation(a["info"], b["info"]) == "conflict"]
    nested = sum(1 for i, a in enumerate(picks) for b in picks[i + 1:]
                 if a["info"] and b["info"] and markets.relation(a["info"], b["info"]) in ("a_covers_b", "b_covers_a"))
    safest = max((p for p in picks if p["prob"] is not None), key=lambda p: p["prob"], default=None)

    # common ground: in the family most codes picked from, the best-priced pick covering every chosen pick
    common = None
    fam_counts = defaultdict(int)
    for p in picks:
        if p["family"]:
            fam_counts[p["family"]] += p["n"]
    if fam_counts and ev is not None:
        fam = max(fam_counts, key=fam_counts.get)
        # most popular pick first; keep adding picks while some market pick still covers all of them, so codes
        # that contradict the majority (Leeds when most say Arsenal) are left out rather than making it impossible
        cands = [(k, v) for k, v in priced.get(fam, {}).items() if not v.get("cond")]
        kept, n_kept = [], 0
        for p in (p for p in picks if p["family"] == fam):
            still = [(k, v) for k, v in cands if markets.covers(v, p["info"])]
            if still:
                cands, n_kept = still, n_kept + p["n"]
                kept.append(p["info"])
        if kept and cands:
            k, v = max(cands, key=lambda kv: (kv[1]["odds"], kv[1]["ret"]))
            common = {"label": k, "odds": v["odds"], "refund": bool(v["push"]), "prob": v["prob"], "ret": v["ret"], "family": fam,
                      "zone": zone(v["odds"]), "covers": n_kept, "of": fam_counts[fam], "n_picks": len(kept),
                      "is_chosen": any(v["win"] == c["win"] and v["push"] == c["push"] and not c.get("maybe") for c in kept),
                      "sel": {"eventId": eid, "marketId": v["mid"], "specifier": v["spec"], "outcomeId": v["oid"]}}
    return {"event_id": eid, "match": first["match"], "league": first["league"], "start_ms": first["start_ms"],
            "n_codes": len(codes), "codes": sorted(codes), "picks": picks, "agree": not conflicts,
            "conflicts": [(a["label"], b["label"]) for a, b in conflicts], "nested": nested, "safest": safest,
            "common": common, "imported": ev is not None, "n_kinds": len(infos)}


def build_code(fixtures_, use="safest", n=3):
    """A short code from the first n fixtures, using each one's safest chosen pick or common-ground pick."""
    legs = []
    for f in fixtures_:
        p = f["common"] if use == "common" else f["safest"]
        if not p or p.get("prob") is None:
            continue
        odds = p["odds"] if use == "common" else (p.get("live_odds") or (p["odds_min"] + p["odds_max"]) / 2)
        legs.append({"match": f["match"], "event_id": f["event_id"], "pick": p["label"], "odds": odds,
                     "prob": p["prob"], "ret": p["ret"] if p.get("ret") else odds * p["prob"],
                     "family": p.get("family"), "sel": p.get("sel"), "refund": bool(p.get("refund"))})
        if len(legs) == n:
            break
    return legs


def candidates(f):
    """Every pick the codes chose on this fixture, plus its common-ground pick, as candidates for target.py.
    Refund picks are left out (their chance isn't the chance of being paid in full)."""
    out, seen = [], set()
    for p in f["picks"] + ([f["common"]] if f.get("common") else []):
        if p.get("prob") is None or p.get("refund") or (p.get("info") or {}).get("push"):
            continue
        odds = p.get("live_odds") or p.get("odds") or (p["odds_min"] + p["odds_max"]) / 2
        if p["label"] in seen:
            continue
        seen.add(p["label"])
        out.append({"match": f["match"], "event_id": f["event_id"], "pick": p["label"], "label": p["label"],
                    "odds": odds, "prob": p["prob"], "ret": odds * p["prob"], "family": p.get("family"),
                    "sel": p.get("sel"), "n": p.get("n"), "codes": p.get("codes") or [],
                    # a chosen pick on a game not imported carries the odds stored with the codes
                    "from_code": not p.get("from_game") and p is not f.get("common")})
    return out
