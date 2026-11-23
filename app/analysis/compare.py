"""Compare booking codes three ways: same picks, related picks on the same games, and same style."""
import math
from collections import Counter

from . import markets
from .codes import leg_info

REL_WEIGHT = {"same": 1.0, "a_covers_b": 0.7, "b_covers_a": 0.7, "overlap": 0.25, "conflict": 0.0, "unrelated": 0.0}


def _by_game(legs):
    g = {}
    for l in legs:
        g.setdefault(l["event_id"], []).append((l, leg_info(l)))
    return g


def aware_overlap(legs_a, legs_b):
    """Same-game similarity that understands nested picks (e.g. 'Arsenal over 1.5' vs 'total over 1.5').
    Returns (score 0..1, per-game details for the games both codes have)."""
    ga, gb = _by_game(legs_a), _by_game(legs_b)
    shared = set(ga) & set(gb)
    details, total = [], 0.0
    for eid in shared:
        best = ("unrelated", None, None)
        for la, ia in ga[eid]:
            for lb, ib in gb[eid]:
                if la["sel_key"] == lb["sel_key"]:
                    rel = "same"
                elif ia and ib:
                    rel = markets.relation(ia, ib)
                else:
                    rel = "unrelated"
                if REL_WEIGHT[rel] > REL_WEIGHT[best[0]]:
                    best = (rel, la, lb)
        total += REL_WEIGHT[best[0]]
        details.append((eid, *best))
    union = len(set(ga) | set(gb))
    return (total / union if union else 0.0), details


def style_similarity(legs_a, legs_b):
    """Cosine similarity of the pick-type mix (market, side, line), ignoring which games they are."""
    ta = Counter(l.get("pick_type") or l["pick"] for l in legs_a)
    tb = Counter(l.get("pick_type") or l["pick"] for l in legs_b)
    dot = sum(ta[k] * tb[k] for k in ta)
    na, nb = math.sqrt(sum(v * v for v in ta.values())), math.sqrt(sum(v * v for v in tb.values()))
    return dot / (na * nb) if na and nb else 0.0


def compare_pairs(legs_by_code, min_any=0.15):
    """Three scores for every pair of codes. legs_by_code = {code: [leg dicts]}."""
    codes = sorted(legs_by_code)
    rows = []
    for i, a in enumerate(codes):
        for b in codes[i + 1:]:
            la, lb = legs_by_code[a], legs_by_code[b]
            sa, sb = {l["sel_key"] for l in la}, {l["sel_key"] for l in lb}
            exact = len(sa & sb) / len(sa | sb) if sa | sb else 0.0
            aware, _ = aware_overlap(la, lb)
            style = style_similarity(la, lb)
            if max(exact, aware, style) >= min_any:
                rows.append({"a": a, "b": b, "shared": len(sa & sb), "exact": exact, "aware": aware, "style": style})
    return sorted(rows, key=lambda r: -max(r["exact"], r["aware"], r["style"]))


def clusters(codes, pairs, threshold=0.5):
    """Group codes linked by game similarity (exact or implication-aware) >= threshold."""
    parent = {c: c for c in codes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for p in pairs:
        if max(p["exact"], p["aware"]) >= threshold:
            parent[find(p["a"])] = find(p["b"])
    groups = {}
    for c in codes:
        groups.setdefault(find(c), []).append(c)
    return [sorted(g) for g in groups.values() if len(g) > 1]
