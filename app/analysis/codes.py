"""Review a booking code against its games.

Works from the saved legs. Where a game's markets have been imported, each leg also gets context:
its rank in the game and the safer / riskier alternatives. Probabilities are the bookmaker's own.
"""
import math
from collections import Counter

from . import markets
from .alternatives import alternatives
from .picks import ZONES, zone

BANDS = [(0.85, "85%+"), (0.70, "70-85%"), (0.55, "55-70%"), (0.0, "under 55%")]
CHEAP_SWAP = 0.15          # a safer pick that costs this much odds or less counts as a "cheap swap"


def band(p):
    for lo, name in BANDS:
        if p >= lo:
            return name
    return BANDS[-1][1]


def leg_info(leg):
    if not leg.get("market_id"):
        return None
    names = (leg.get("match") or "").split(" v ", 1)
    names = (names + [""])[:2]
    return markets.leg_info(leg["market_id"], leg.get("specifier") or "", leg["pick"], tuple(names))


def priced_lookup(get_event, cache):
    """priced_for(event_id, family) for combine_same_game, sharing leg_context's cache."""
    def priced_for(eid, family):
        if ("ev", eid) not in cache:
            cache[("ev", eid)] = get_event(eid)
        ev = cache[("ev", eid)]
        if ev is None:
            return None
        key = ("priced", eid, family)
        if key not in cache:
            cache[key] = markets.build_priced(ev, family)
        return cache[key]
    return priced_for


def leg_context(get_event, leg, cache, full=True):
    """What else was on offer in this leg's game, and where the leg sits among it.
    get_event(event_id) returns the imported game dict or None. full=False skips the alternatives and rank,
    for when only the leg's own chance and return are needed."""
    info = leg_info(leg)
    out = {"info": info, "has_data": False, "family": info["family"] if info else None}
    if not info:
        out["why"] = "market not modelled"
        return out
    key = ("ev", leg["event_id"])
    if key not in cache:
        cache[key] = get_event(leg["event_id"])
    ev = cache[key]
    if ev is None:
        out["why"] = "game not imported"
        return out
    fkey = ("priced", leg["event_id"], info["family"])
    if fkey not in cache:
        cache[fkey] = markets.build_priced(ev, info["family"])
    priced = cache[fkey]
    if info.get("early"):
        # not a priced pick of its own: compare it by the results it surely and possibly wins on
        if leg.get("prob") is None:
            out["why"] = "no chance given for this pick"
            return out
        base = {**info, "odds": leg["odds"], "prob": leg["prob"], "ret": leg["odds"] * leg["prob"]}
        if not full:
            out.update(has_data=True, base=base)
            return out
        safer, riskier = alternatives(priced, base=base)
        out.update(has_data=True, base=base, rank=None, n=len(priced), safer=safer, riskier=riskier,
                   cheap_swap=next(((k, v) for k, v in safer if leg["odds"] - v["odds"] <= CHEAP_SWAP and
                                    v["prob"] > base["prob"]), None))
        return out
    base = priced.get(info["label"])
    if base is None:
        out["why"] = "pick not in imported odds (suspended, or only league markets imported)"
        return out
    if not full:
        out.update(has_data=True, base=base)
        return out
    safer, riskier = alternatives(priced, info["label"])
    out.update(has_data=True, base=base, rank=1 + sum(1 for v in priced.values() if v["prob"] > base["prob"]),
               n=len(priced), safer=safer, riskier=riskier,
               cheap_swap=next(((k, v) for k, v in safer if leg["odds"] - v["odds"] <= CHEAP_SWAP and
                                v["prob"] > base["prob"]), None))
    return out


def with_game_odds(legs_ctx):
    """Legs with refund picks corrected from the imported game: SportyBet's figure for a draw-no-bet leg is
    the chance of winning when there's no draw; the game's own prices give the chance of winning outright and
    the refund chance. Returns (adjusted legs, number of refund legs that couldn't be corrected)."""
    out, unresolved = [], 0
    for leg, ctx in legs_ctx:
        leg = dict(leg)
        base, info = ctx.get("base"), ctx.get("info")
        if base and base.get("push") and not base.get("cond"):
            leg.update(prob=base["prob"], ret=base["ret"], push_prob=base.get("push_prob"))
        elif info and info.get("push"):
            unresolved += 1
        out.append(leg)
    return out, unresolved


def combine_same_game(legs, priced_for=None):
    """Legs on the same game aren't independent. Each game's legs become one 'unit' with the chance that all of
    them win together. Exact when one leg implies the others, when they contradict, or when the combination is a
    priced market in the game; otherwise the chances are multiplied and the unit is marked as an estimate.
    priced_for(event_id, family) returns that game's priced picks, or None."""
    groups = {}
    for l in legs:
        groups.setdefault(l["event_id"], []).append(l)
    units = []
    for eid, ls in groups.items():
        if len(ls) == 1:
            l = ls[0]
            units.append({"legs": ls, "odds": l["odds"], "prob": l.get("prob"),
                          "ret": l.get("ret") or (l["odds"] * l["prob"] if l.get("prob") is not None else None),
                          "how": "single"})
            continue
        odds = math.prod(l["odds"] for l in ls)
        infos = [leg_info(l) for l in ls]
        probs = [l.get("prob") for l in ls]
        prob, how = None, "estimate"
        if all(infos) and len({i["family"] for i in infos}) == 1 and not any(i["push"] for i in infos) \
                and not any(i.get("maybe") for i in infos):
            both = infos[0]["win"]
            for i in infos[1:]:
                both &= i["win"]
            if both == 0:
                prob, how = 0.0, "contradiction"
            else:
                inside = [p for i, p in zip(infos, probs) if i["win"] == both and p is not None]
                if inside:
                    prob, how = min(inside), "exact"
                elif priced_for:
                    priced = priced_for(eid, infos[0]["family"]) or {}
                    hit = next((v for v in priced.values() if not v["push"] and v["win"] == both), None)
                    if hit:
                        prob, how = hit["prob"], "exact"
        ret = odds * prob if prob is not None else None
        if prob is None and all(p is not None for p in probs):
            prob = math.prod(probs)
            # as an estimate the legs are treated as independent, so their returns (refunds included) multiply too
            rets = [l.get("ret") if l.get("ret") is not None else l["odds"] * l["prob"] for l in ls]
            ret = math.prod(rets)
        units.append({"legs": ls, "odds": odds, "prob": prob, "how": how, "ret": ret})
    return units


def summarise(legs, priced_for=None):
    units = combine_same_game(legs, priced_for)
    probs = [u["prob"] for u in units if u["prob"] is not None]
    odds = math.prod(l["odds"] for l in legs) if legs else 0
    joint = math.prod(probs) if len(probs) == len(units) and units else None
    # average return of a code = product of each unit's average return (a refunded leg counts as odds 1)
    exp_ret = math.prod(u["ret"] for u in units) if joint is not None and all(u["ret"] is not None for u in units) \
        else None
    same_game = [u for u in units if len(u["legs"]) > 1]
    bands = Counter(band(l["prob"]) for l in legs if l.get("prob") is not None)
    types = Counter(l.get("pick_type") or f'{l.get("market", "")}: {l.get("pick", "")}' for l in legs)
    weakest = sorted((l for l in legs if l.get("prob")), key=lambda l: l["prob"])[:5]
    tox_grade = "A"
    tox_margin = 0.0
    breakeven_beat = 0.0
    if exp_ret is not None:
        tox_margin = max(0.0, (1.0 - exp_ret) * 100.0)
        breakeven_beat = max(0.0, ((1.0 / max(1e-6, exp_ret)) - 1.0) * 100.0)
        if exp_ret >= 0.90:
            tox_grade = "A"
        elif exp_ret >= 0.80:
            tox_grade = "B"
        elif exp_ret >= 0.65:
            tox_grade = "C"
        elif exp_ret >= 0.45:
            tox_grade = "D"
        else:
            tox_grade = "F"

    # Identify individual toxic legs (where return < 0.91 or single leg house margin > 9%)
    toxic_legs = [
        l for l in legs
        if l.get("ret") is not None and l["ret"] < 0.91 or (l.get("prob") and l.get("odds") and l["odds"] * l["prob"] < 0.91)
    ]

    return {
        "n_legs": len(legs), "n_games": len({l["event_id"] for l in legs}),
        "leagues": len({l["league"] for l in legs}),
        "total_odds": odds, "joint_prob": joint,
        "fair_odds": (1 / joint) if joint else None,
        "exp_return": exp_ret,
        "toxicity_grade": tox_grade,
        "toxicity_margin_pct": tox_margin,
        "breakeven_beat_pct": breakeven_beat,
        "toxic_legs": toxic_legs,
        "n_refund": sum(1 for l in legs if l.get("push_prob")),
        "same_game": same_game,
        "same_game_estimates": sum(1 for u in same_game if u["how"] == "estimate"),
        "same_game_conflicts": sum(1 for u in same_game if u["how"] == "contradiction"),
        "bands": [(name, bands.get(name, 0)) for _, name in BANDS],
        "zones": [(label, sum(1 for l in legs if zone(l["odds"]) == key)) for key, label, _, _ in ZONES],
        "types": types.most_common(),
        "weakest": weakest,
        "first": min((l["start_ms"] for l in legs if l.get("start_ms")), default=None),
        "last": max((l["start_ms"] for l in legs if l.get("start_ms")), default=None),
    }


def improve(legs, contexts, keep=None, swap=False, min_odds=1.10):
    """A version of the code with a higher chance of winning.
    swap: replace each leg with the most likely safer pick on the same game that still pays at least min_odds
          (a safer pick does at least as well as the original in every result).
    keep: then keep only the `keep` most likely legs.
    Returns the new legs; each has 'changed' (swapped), and 'was' (the original pick) when swapped."""
    out = []
    for l, c in zip(legs, contexts):
        new = {**l, "changed": False}
        if swap and c.get("has_data") and c.get("safer"):
            cands = [(k, v) for k, v in c["safer"] if v["odds"] >= min_odds and not v.get("cond")]
            if cands:
                k, v = max(cands, key=lambda kv: (kv[1]["prob"], kv[1]["odds"]))
                if v["prob"] > (l.get("prob") or 0) + 1e-9:
                    new.update(changed=True, was=f'{l["market"]}: {l["pick"]}', label=k, odds=v["odds"],
                               prob=v["prob"], ret=v["ret"], push_prob=v.get("push_prob"),
                               market_id=v["mid"], specifier=v["spec"], outcome_id=v["oid"])
        new.setdefault("label", f'{l["market"]}: {l["pick"]}')
        out.append(new)
    if keep and keep < len(out):
        ranked = sorted((l for l in out if l.get("prob") is not None), key=lambda l: -l["prob"])
        kept = {id(l) for l in ranked[:keep]}
        out = [l for l in out if id(l) in kept]
    return out


def drop_weakest(legs, k):
    """Odds / chance if the k weakest legs were removed (probabilities assumed independent)."""
    keep = sorted((l for l in legs if l.get("prob")), key=lambda l: l["prob"])[k:]
    if not keep:
        return None
    return math.prod(l["odds"] for l in keep), math.prod(l["prob"] for l in keep)
