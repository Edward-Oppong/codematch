"""Personal Calibration Engine — Phase 5.

Measures the user's actual win rate against SportyBet's implied probability,
broken down by market family. This converts SportyBet's margin into the user's
own empirical model: if SB says 60% and you win 65%, that edge is real and
usable in Kelly sizing.

Key outputs:
  - market_edge(settled_legs) → per-market edge summary with significance
  - calibrated_prob(market, stated_prob, settled_legs) → user's true prob estimate
  - kelly_tier(settled_legs) → 'flat' | 'calibrated' | 'ready'
  - significance(n, wins, stated) → Wilson CI and verdict
"""
import math
from collections import defaultdict


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum bets in a market before calibration is used instead of flat sizing
MIN_BETS_FOR_CALIBRATION = 50
# Minimum for a "ready" verdict with tight confidence intervals
MIN_BETS_FOR_VERDICT = 200

# Probability buckets used for intra-market calibration
PROB_EDGES = [0.0, 0.3, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01]

# Market family normalization: map raw market strings → canonical family
_FAMILY_MAP = [
    (["corners", "corner"], "Corners"),
    (["booking", "card", "yellow", "red"], "Bookings"),
    (["goalkeeper", "keeper", "save"], "Goalkeeper & Saves"),
    (["player", "scorer", "goalscorer", "anytime goal", "assist"], "Player Props (Goalscorer/Shots)"),
    (["foul", "offside", "shot", "tackle", "throw-in"], "Match Stats (Fouls/Shots)"),
    (["both teams", "btts", "bts", "gg/ng", "gg", "ng"], "Both Teams to Score (GG/NG)"),
    (["handicap", "asian"], "Handicap"),
    (["correct score", "exact score"], "Correct Score"),
    (["half", "ht/ft", "halftime", "1st half", "2nd half", "halves", "either half", "both halves"], "Half-Time & Halves"),
    (["win to nil", "clean sheet"], "Clean Sheet / Win to Nil"),
    (["1up", "2up", "double chance", "dnb", "no bet", "draw no bet"], "Double Chance & Draw No Bet"),
    (["combos", "combo", " & over", " & under", " & gg", " or over", " or gg"], "Combos & Multi-Picks"),
    (["1x2", "result", "home win", "away win", "draw"], "1X2 & Match Result"),
    (["over", "under", "goals", "total", "bounds"], "Totals & Over/Under"),
]


def _market_family(market: str) -> str:
    m = market.lower()
    for keywords, family in _FAMILY_MAP:
        if any(k in m for k in keywords):
            return family
    return "Other"


# ---------------------------------------------------------------------------
# Wilson score confidence interval
# ---------------------------------------------------------------------------

def wilson_ci(n: int, k: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for k successes in n trials."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def significance_verdict(n: int, wins: int, stated_prob: float) -> dict:
    """
    Returns a verdict dict:
      n, wins, win_rate, stated, edge_pct,
      ci_low, ci_high,
      significant (bool — CI excludes stated_prob),
      tier ('not_enough' | 'early' | 'confident'),
      message (human-readable string)
    """
    if n == 0:
        return {"n": 0, "wins": 0, "win_rate": 0.0, "stated": stated_prob,
                "edge_pct": 0.0, "ci_low": 0.0, "ci_high": 1.0,
                "significant": False, "tier": "not_enough",
                "message": "No data yet."}

    win_rate = wins / n
    ci_low, ci_high = wilson_ci(n, wins)
    edge_pct = (win_rate - stated_prob) * 100.0
    # Significant if the CI clearly excludes stated_prob
    significant = ci_low > stated_prob or ci_high < stated_prob

    if n < MIN_BETS_FOR_CALIBRATION:
        tier = "not_enough"
        msg = f"Need {MIN_BETS_FOR_CALIBRATION - n} more bets to use calibration."
    elif n < MIN_BETS_FOR_VERDICT:
        tier = "early"
        msg = f"Early signal ({n} bets). CI still wide; {MIN_BETS_FOR_VERDICT - n} more for confident verdict."
    else:
        tier = "confident"
        if significant and edge_pct > 0:
            msg = f"You beat SportyBet's pricing by {edge_pct:+.1f}% here (95% CI excludes 0)."
        elif significant and edge_pct < 0:
            msg = f"You underperform SportyBet's pricing by {edge_pct:+.1f}% here — avoid this market."
        else:
            msg = "No significant edge detected. Performance matches SportyBet's pricing."

    return {
        "n": n, "wins": wins, "win_rate": win_rate, "stated": stated_prob,
        "edge_pct": edge_pct, "ci_low": ci_low, "ci_high": ci_high,
        "significant": significant, "tier": tier, "message": msg,
    }


# ---------------------------------------------------------------------------
# Main calibration engine
# ---------------------------------------------------------------------------

def market_edge(settled_legs: list) -> list[dict]:
    """
    Group settled legs by market family. For each family return:
      family, n, wins, win_rate, avg_stated_prob, edge_pct,
      ci_low, ci_high, significant, tier, message,
      calibrated_kelly_boost (multiplier to apply to Kelly when edge > 0 and significant)

    settled_legs: list of dicts with keys: market, prob, status ('won'|'lost'|'void'), sel_key
    """
    by_family: dict[str, list] = defaultdict(list)
    seen_keys: set = set()

    for leg in settled_legs:
        # De-duplicate: same pick in multiple codes counts once
        key = leg.get("sel_key") or (leg.get("event_id"), leg.get("market_id"),
                                     leg.get("specifier"), leg.get("outcome_id"))
        if key in seen_keys:
            continue
        seen_keys.add(key)

        if leg.get("status") not in ("won", "lost"):
            continue
        if leg.get("prob") is None or leg.get("market") is None:
            continue

        family = _market_family(leg["market"])
        by_family[family].append(leg)

    rows = []
    for family, legs in sorted(by_family.items()):
        n = len(legs)
        wins = sum(1 for l in legs if l["status"] == "won")
        avg_stated = sum(l["prob"] for l in legs) / n if n else 0.0
        v = significance_verdict(n, wins, avg_stated)

        # Kelly boost: if we have a confident positive edge, scale Kelly up
        # (but cap at 2× to prevent wild oversizing from small samples)
        if v["significant"] and v["edge_pct"] > 0 and v["tier"] == "confident":
            # True prob / stated prob is the adjustment factor
            boost = min(2.0, v["win_rate"] / avg_stated) if avg_stated > 0 else 1.0
        else:
            boost = 1.0

        rows.append({
            "family": family,
            "n": n,
            "wins": wins,
            "win_rate": v["win_rate"],
            "avg_stated": avg_stated,
            "edge_pct": v["edge_pct"],
            "ci_low": v["ci_low"],
            "ci_high": v["ci_high"],
            "significant": v["significant"],
            "tier": v["tier"],
            "message": v["message"],
            "kelly_boost": boost,
        })

    return rows


def calibrated_prob(market: str, stated_prob: float, settled_legs: list) -> float:
    """
    Returns the best probability estimate for a given market pick.
    - If we have enough settled bets in this family with similar prob: use empirical rate
    - Otherwise: return stated_prob unchanged (no calibration = no change)
    """
    family = _market_family(market)
    seen_keys: set = set()
    bucket_legs = []

    for leg in settled_legs:
        key = leg.get("sel_key") or (leg.get("event_id"), leg.get("market_id"),
                                     leg.get("specifier"), leg.get("outcome_id"))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        if leg.get("status") not in ("won", "lost"):
            continue
        if leg.get("prob") is None or leg.get("market") is None:
            continue
        if _market_family(leg["market"]) != family:
            continue
        # Find legs in a similar prob bucket (±15pp)
        if abs(leg["prob"] - stated_prob) <= 0.15:
            bucket_legs.append(leg)

    n = len(bucket_legs)
    if n < MIN_BETS_FOR_CALIBRATION:
        return stated_prob  # not enough data — use stated

    wins = sum(1 for l in bucket_legs if l["status"] == "won")
    empirical = wins / n
    # Blend 70% empirical / 30% stated to avoid overfitting on small samples
    blend = 0.7 * empirical + 0.3 * stated_prob if n < MIN_BETS_FOR_VERDICT else empirical
    return round(blend, 4)


def kelly_tier(settled_legs: list) -> str:
    """
    Returns the Kelly tier the user is in overall:
      'flat'        — fewer than MIN_BETS_FOR_CALIBRATION settled legs total
      'calibrated'  — enough for calibration but not full confidence
      'ready'       — enough for confident verdict in at least one market
    """
    seen_keys: set = set()
    n = 0
    for leg in settled_legs:
        key = leg.get("sel_key") or (leg.get("event_id"),)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        if leg.get("status") in ("won", "lost"):
            n += 1

    if n < MIN_BETS_FOR_CALIBRATION:
        return "flat"
    if n < MIN_BETS_FOR_VERDICT:
        return "calibrated"
    return "ready"


def overall_edge_summary(market_rows: list) -> dict:
    """
    Aggregate summary across all markets for the dashboard figures strip.
    """
    total_n = sum(r["n"] for r in market_rows)
    total_wins = sum(r["wins"] for r in market_rows)
    if total_n == 0:
        return {"n": 0, "win_rate": 0.0, "avg_stated": 0.0, "edge_pct": 0.0,
                "ci_low": 0.0, "ci_high": 1.0, "significant": False}

    avg_stated = sum(r["avg_stated"] * r["n"] for r in market_rows) / total_n
    v = significance_verdict(total_n, total_wins, avg_stated)
    return {
        "n": total_n,
        "win_rate": v["win_rate"],
        "avg_stated": avg_stated,
        "edge_pct": v["edge_pct"],
        "ci_low": v["ci_low"],
        "ci_high": v["ci_high"],
        "significant": v["significant"],
        "tier": v["tier"],
        "message": v["message"],
    }
