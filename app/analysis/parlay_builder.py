"""Custom Parlay Generation Algorithms for CodeMatch.

Provides 4 distinct algorithmic accumulator generation strategies:
1. Target Odds Optimizer (Dynamic Knapsack with minimal compounding house margin)
2. Time-Staggered Hedging Engine (Non-overlapping kickoff timeline for progressive cashout/hedging)
3. Zone-Structured Engine (Anchor + Engine + Multiplier portfolio formulas)
4. Round-Robin System Engine (Loss-resistant multi-slip permutations with break-even calculations)
"""
import itertools
import math
from typing import Any, Dict, List, Optional, Tuple

from . import flow, target
from .picks import zone


def _clean_candidates(games: List[List[Dict[str, Any]]], min_chance: float = 0.0) -> List[List[Dict[str, Any]]]:
    """Ensure candidates are normalized, valid, have positive odds and meet minimum probability."""
    clean = []
    min_p = max(0.0, min(float(min_chance), 0.99))
    for g in games:
        valid = [
            c for c in g
            if c.get("prob") is not None and c["prob"] >= min_p and float(c.get("odds", 0.0)) > 1.0
            and not c.get("refund")
        ]
        if valid:
            clean.append(valid)
    return clean


# ─────────────────────────────────────────────────────────────────────────────
# 1. Target Odds Optimizer
# ─────────────────────────────────────────────────────────────────────────────

def build_target_odds(
    games: List[List[Dict[str, Any]]],
    target_odds: float = 3.50,
    min_legs: int = 2,
    max_legs: int = 8,
    min_chance: float = 0.50
) -> Dict[str, Any]:
    """Build an accumulator reaching target_odds with the highest joint probability and lowest house cut."""
    clean = _clean_candidates(games, min_chance=min_chance)
    if not clean:
        return {"legs": [], "totals": None, "stacked": None, "reached": False, "target": target_odds}

    opt = flow.optimize_pool(
        clean,
        target_odds=target_odds,
        min_legs=min_legs,
        max_legs=max_legs,
        min_chance=min_chance,
        mode="target"
    )
    return {
        "strategy": "target_odds",
        "target": target_odds,
        "legs": opt.get("legs", []),
        "totals": opt.get("totals"),
        "stacked": opt.get("stacked"),
        "n_games": opt.get("n_games", 0),
        "reached": opt.get("reached", False)
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. Time-Staggered Hedging Engine
# ─────────────────────────────────────────────────────────────────────────────

def build_time_staggered(
    games: List[List[Dict[str, Any]]],
    n_legs: int = 4,
    min_gap_mins: int = 105,
    min_chance: float = 0.55
) -> Dict[str, Any]:
    """Select a sequence of non-overlapping matches ordered by kickoff time to maximize cashout and hedging opportunities.
    
    Each game finishes (or is near completion) before the next starts, allowing the bettor
    to lock in profit after each leg or accept SportyBet's exponential cashout offer.
    """
    clean = _clean_candidates(games, min_chance=min_chance)
    if not clean:
        return {"legs": [], "totals": None, "timeline": [], "n_available": 0}

    # Extract best candidate from each fixture (highest expected return / probability)
    best_per_game = []
    for g in clean:
        best_cand = max(g, key=lambda c: (c.get("ret", 0.0), c.get("prob", 0.0)))
        start_ms = best_cand.get("start_ms") or 0
        if start_ms > 0:
            best_per_game.append(best_cand)

    best_per_game.sort(key=lambda c: c.get("start_ms", 0))

    # Greedy search for a chain of n_legs with >= min_gap_mins between kickoffs
    gap_ms = min_gap_mins * 60 * 1000
    chosen_chain: List[Dict[str, Any]] = []

    # Try starting from the earliest game, then find subsequent games with the time gap
    for start_idx in range(len(best_per_game)):
        candidate_chain = [best_per_game[start_idx]]
        last_ms = candidate_chain[0]["start_ms"]

        for cand in best_per_game[start_idx + 1:]:
            if cand["start_ms"] >= last_ms + gap_ms:
                candidate_chain.append(cand)
                last_ms = cand["start_ms"]
                if len(candidate_chain) == n_legs:
                    break

        if len(candidate_chain) > len(chosen_chain):
            chosen_chain = candidate_chain
            if len(chosen_chain) == n_legs:
                break

    if not chosen_chain:
        return {"legs": [], "totals": None, "timeline": [], "n_available": len(best_per_game)}

    # Build progressive timeline: Cashout multiple and hedge recommendation after each leg
    timeline = []
    cum_odds = 1.0
    cum_prob = 1.0
    cum_ret = 1.0

    for idx, leg in enumerate(chosen_chain, 1):
        cum_odds *= leg["odds"]
        cum_prob *= leg.get("prob") or 1.0
        cum_ret *= leg.get("ret") or 1.0
        
        # Estimate cashout offer factor (approx 85-90% of fair value after this leg hits)
        cashout_factor = cum_odds * 0.88 if idx < len(chosen_chain) else cum_odds

        timeline.append({
            "step": idx,
            "leg": leg,
            "cum_odds": round(cum_odds, 2),
            "cum_prob": round(cum_prob, 3),
            "cashout_estimate": round(cashout_factor, 2),
            "is_final": idx == len(chosen_chain)
        })

    totals = target.totals(chosen_chain)
    return {
        "strategy": "time_staggered",
        "legs": chosen_chain,
        "totals": totals,
        "timeline": timeline,
        "min_gap_mins": min_gap_mins,
        "n_available": len(best_per_game)
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. Zone-Structured Engine (Anchor - Engine - Multiplier)
# ─────────────────────────────────────────────────────────────────────────────

PRESETS = {
    "anchor_engine": {
        "name": "Anchor + Engine (Balanced 4-Leg)",
        "description": "2 ultra-safe Bankers (odds 1.15-1.28) + 1 Solid Value Engine (1.45-1.70) + 1 High-EV Multiplier (1.75+)",
        "tiers": [
            {"name": "Anchor (Safe Banker)", "min_odds": 1.15, "max_odds": 1.30, "min_prob": 0.75, "count": 2},
            {"name": "Engine (Core Value)", "min_odds": 1.40, "max_odds": 1.70, "min_prob": 0.55, "count": 1},
            {"name": "Multiplier (EV Booster)", "min_odds": 1.70, "max_odds": 3.00, "min_prob": 0.35, "count": 1},
        ]
    },
    "high_chance_double": {
        "name": "High-Chance Double (2-Leg Banker)",
        "description": "2 ultra-high probability selections combined for safe compounding (combined odds ~1.60 - 1.95)",
        "tiers": [
            {"name": "Primary Anchor", "min_odds": 1.20, "max_odds": 1.42, "min_prob": 0.70, "count": 1},
            {"name": "Secondary Anchor", "min_odds": 1.25, "max_odds": 1.45, "min_prob": 0.68, "count": 1},
        ]
    },
    "balanced_quad": {
        "name": "Balanced Quad (4-Leg Value Parlay)",
        "description": "4 steady single picks in the sweet-spot 1.30 - 1.55 range where bookmaker margins are modest",
        "tiers": [
            {"name": "Value Leg", "min_odds": 1.30, "max_odds": 1.55, "min_prob": 0.62, "count": 4},
        ]
    },
    "underdog_boost": {
        "name": "Underdog Plus-Money Booster",
        "description": "2 High-probability Anchors paired with 1 mispriced underdog or plus-money line (odds > 2.00)",
        "tiers": [
            {"name": "Safety Anchor", "min_odds": 1.18, "max_odds": 1.35, "min_prob": 0.72, "count": 2},
            {"name": "Underdog Edge", "min_odds": 2.00, "max_odds": 3.50, "min_prob": 0.30, "count": 1},
        ]
    }
}


def build_zone_structured(
    games: List[List[Dict[str, Any]]],
    preset_key: str = "anchor_engine"
) -> Dict[str, Any]:
    """Build a parlay according to a structural risk-portfolio formula (Anchors, Engines, Multipliers)."""
    preset = PRESETS.get(preset_key, PRESETS["anchor_engine"])
    clean = _clean_candidates(games)
    if not clean:
        return {"legs": [], "totals": None, "preset": preset, "satisfied": False}

    used_event_ids = set()
    selected_legs = []

    for tier in preset["tiers"]:
        needed = tier["count"]
        min_o = tier["min_odds"]
        max_o = tier["max_odds"]
        min_p = tier["min_prob"]

        # Find qualifying candidates from unused fixtures
        tier_candidates = []
        for g in clean:
            first_cand = g[0]
            eid = first_cand.get("event_id")
            if eid in used_event_ids:
                continue

            for c in g:
                if min_o <= c["odds"] <= max_o and (c.get("prob") or 0) >= min_p:
                    tier_candidates.append({**c, "tier_name": tier["name"]})

        # Rank candidates by Expected Return, then probability
        tier_candidates.sort(key=lambda c: (-(c.get("ret") or 0), -(c.get("prob") or 0)))

        for c in tier_candidates:
            if c["event_id"] not in used_event_ids:
                used_event_ids.add(c["event_id"])
                selected_legs.append(c)
                needed -= 1
                if needed <= 0:
                    break

    satisfied = len(selected_legs) == sum(t["count"] for t in preset["tiers"])
    totals = target.totals(selected_legs) if selected_legs else None

    return {
        "strategy": "zone_structured",
        "preset_key": preset_key,
        "preset": preset,
        "legs": selected_legs,
        "totals": totals,
        "satisfied": satisfied
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. Round-Robin & Permutation Engine (Loss-Resistant Slips)
# ─────────────────────────────────────────────────────────────────────────────

def build_round_robin(
    games: List[List[Dict[str, Any]]],
    pool_size: int = 5,
    fold_size: int = 3,
    unit_stake: float = 10.0,
    min_chance: float = 0.55
) -> Dict[str, Any]:
    """Generate all N-fold combinations from a pool of M high-value selections.
    
    Computes payout scenarios, break-even thresholds (e.g. 'Must win 3 of 5 to profit'),
    and prepares individual booking codes ready for SportyBet.
    """
    clean = _clean_candidates(games, min_chance=min_chance)
    if not clean:
        return {"pool": [], "combinations": [], "stats": None}

    # Extract 1 best pick per game
    pool_candidates = []
    for g in clean:
        best_cand = max(g, key=lambda c: (c.get("ret", 0.0), c.get("prob", 0.0)))
        pool_candidates.append(best_cand)

    # Sort by probability descending to pick the strongest M games
    pool_candidates.sort(key=lambda c: (-(c.get("prob") or 0), -(c.get("ret") or 0)))
    selected_pool = pool_candidates[:max(3, min(pool_size, 8))]

    m = len(selected_pool)
    k = max(2, min(fold_size, m - 1))

    # Generate all combinations of size k from pool m
    combos = []
    combo_indices = list(itertools.combinations(range(m), k))
    total_bets = len(combo_indices)
    total_staked = total_bets * unit_stake

    combo_payouts = []
    for idx_tuple in combo_indices:
        combo_legs = [selected_pool[i] for i in idx_tuple]
        c_odds = math.prod(l["odds"] for l in combo_legs)
        c_prob = math.prod(l.get("prob") or 1.0 for l in combo_legs)
        payout = c_odds * unit_stake
        combo_payouts.append(payout)
        combos.append({
            "indices": idx_tuple,
            "legs": combo_legs,
            "odds": round(c_odds, 2),
            "prob": round(c_prob, 3),
            "payout": round(payout, 2),
            "selections": [l.get("sel") for l in combo_legs if l.get("sel")]
        })

    # Scenario Simulation: What is the payout if exactly W games win?
    scenarios = []
    min_profit_w = None

    for w in range(k, m + 1):
        # Average payout if exactly w games win
        sub_combos = list(itertools.combinations(range(w), k))
        n_winning_slips = len(sub_combos)
        avg_slip_odds = (sum(c["odds"] for c in combos) / len(combos)) if combos else 0
        est_return = n_winning_slips * avg_slip_odds * unit_stake
        profit = est_return - total_staked

        if profit > 0 and min_profit_w is None:
            min_profit_w = w

        scenarios.append({
            "wins": w,
            "winning_slips": n_winning_slips,
            "estimated_return": round(est_return, 2),
            "net_profit": round(profit, 2),
            "is_profitable": profit > 0
        })

    max_payout = sum(combo_payouts) if combo_payouts else 0.0

    return {
        "strategy": "round_robin",
        "pool": selected_pool,
        "pool_size": m,
        "fold_size": k,
        "n_combinations": total_bets,
        "unit_stake": unit_stake,
        "total_staked": round(total_staked, 2),
        "max_payout": round(max_payout, 2),
        "break_even_wins": min_profit_w or k,
        "combinations": combos,
        "scenarios": scenarios
    }
