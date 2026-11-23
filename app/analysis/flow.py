"""Unified Analysis & Optimization Pipeline for CodeMatch.

Provides a single coherent flow:
1. Ingest & Normalize (Raw picks from codes, fixtures, leagues, or screeners)
2. Audit (Margin checks, contradiction detection, stale odds, expected return)
3. Optimize (Target odds search, safer alternatives swap, trimming weakest)
4. Export / Dispatch (SportyBet booking payload preparation)
"""
import math
from typing import Any, Dict, List, Optional, Tuple

from . import markets, target
from .picks import zone


def normalize_candidate(raw: Dict[str, Any], event_id: Optional[str] = None, match: Optional[str] = None) -> Dict[str, Any]:
    """Normalize a candidate pick from any source into a consistent dictionary."""
    eid = raw.get("event_id") or raw.get("eventId") or event_id or ""
    m_name = raw.get("match") or match or raw.get("matchName") or ""
    label = raw.get("label") or raw.get("pick") or f'{raw.get("market", "")}: {raw.get("pick", "")}'
    odds = float(raw.get("live_odds") or raw.get("odds") or 0.0)
    prob = raw.get("prob")
    prob_f = float(prob) if prob is not None else None
    ret = raw.get("ret")
    if ret is None and prob_f is not None and odds > 0:
        ret = odds * prob_f

    sel = raw.get("sel")
    if not sel and raw.get("marketId") and raw.get("outcomeId"):
        sel = {
            "eventId": eid,
            "marketId": str(raw.get("marketId")),
            "specifier": str(raw.get("specifier") or ""),
            "outcomeId": str(raw.get("outcomeId"))
        }

    return {
        "event_id": eid,
        "match": m_name,
        "label": label,
        "pick": raw.get("pick") or label,
        "odds": odds,
        "prob": prob_f,
        "ret": ret,
        "family": raw.get("family"),
        "sel": sel,
        "zone": raw.get("zone") or zone(odds),
        "from_code": bool(raw.get("from_code")),
        "refund": bool(raw.get("refund") or raw.get("push") or (raw.get("info") or {}).get("push")),
        "codes": list(raw.get("codes") or []),
        "n": raw.get("n", 1),
    }


def audit_candidates(games: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Audit a pool of candidate games and identify potential issues."""
    n_games = len(games)
    total_cands = sum(len(g) for g in games)
    stale_count = sum(1 for g in games for c in g if c.get("from_code"))
    refund_count = sum(1 for g in games for c in g if c.get("refund"))
    
    # Check if high margin picks (> 8% bookmaker edge) dominate
    high_margin = sum(1 for g in games for c in g if c.get("ret") is not None and c["ret"] < 0.92)

    return {
        "n_games": n_games,
        "total_candidates": total_cands,
        "stale_candidates": stale_count,
        "refund_candidates": refund_count,
        "high_margin_candidates": high_margin,
        "has_data": total_cands > 0,
    }


def optimize_pool(
    games: List[List[Dict[str, Any]]],
    target_odds: Optional[float] = None,
    min_legs: int = 1,
    max_legs: Optional[int] = None,
    min_chance: float = 0.0,
    mode: str = "target"
) -> Dict[str, Any]:
    """Single unified optimizer for any candidate pool.
    
    Modes:
      - 'target': Finds the highest-chance combination reaching target_odds.
      - 'safest': Picks the single safest selection from each fixture up to max_legs.
    """
    clean_games: List[List[Dict[str, Any]]] = []
    min_p = max(0.0, min(min_chance, 0.99))

    for g in games:
        filtered = [
            c for c in g
            if c.get("prob") is not None and c["prob"] >= min_p and not c.get("refund") and c.get("odds", 0) > 1.0
        ]
        if filtered:
            clean_games.append(filtered)

    if not clean_games:
        return {"legs": [], "totals": None, "stacked": None, "n_games": 0, "reached": False}

    chosen_legs: List[Dict[str, Any]] = []
    stacked_totals = None

    if mode == "safest":
        # Sort each game by probability descending, take the safest
        safest_each = [max(g, key=lambda c: (c["prob"], c["odds"])) for g in clean_games]
        safest_each.sort(key=lambda c: -c["prob"])
        limit = max_legs or len(safest_each)
        chosen_legs = safest_each[:limit]
    else:
        # Default: target odds optimization
        goal = float(target_odds or 2.0)
        goal = min(max(goal, 1.01), 10000.0)

        if min_legs > 1:
            chosen_legs = target.best_with_min_legs(clean_games, goal, min_legs) or []
        elif max_legs:
            legs_by_count = target.best_by_legs(clean_games, goal, max_legs)
            if legs_by_count:
                chosen_legs = max(legs_by_count, key=lambda k_legs: math.prod(l["prob"] for l in k_legs[1]))[1]
            else:
                chosen_legs = []
        else:
            chosen_legs = target.best_for_odds(clean_games, goal) or []

        # Stacking comparison
        stacked = target.stack_safest(clean_games, goal)
        if stacked:
            stacked_totals = target.totals(stacked)

    chosen_legs.sort(key=lambda l: -l["prob"])
    t = target.totals(chosen_legs)

    return {
        "legs": chosen_legs,
        "totals": t,
        "stacked": stacked_totals,
        "n_games": len(clean_games),
        "reached": bool(chosen_legs and (not target_odds or (t and t["odds"] >= target_odds * target.TOL))),
    }
