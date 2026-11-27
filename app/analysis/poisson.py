"""Implied Poisson Goal Model — derives team expected goals (xG) from SportyBet's own 1X2 and O/U 2.5 odds.

No external team stats or APIs required: SportyBet's main lines (1X2 + Over/Under 2.5) uniquely
determine a pair of Poisson scoring rates (lambda_home, lambda_away) via coarse-to-fine search.
Those rates then price all other goal, BTTS, and double-chance lines for comparison against
SportyBet's posted probabilities.
"""
import math
import re

MAX_GOALS = 8
_FACTORIALS = [math.factorial(k) for k in range(MAX_GOALS + 1)]


def _poisson_pmf(lam: float) -> list[float]:
    e = math.exp(-lam)
    return [e * (lam ** k) / _FACTORIALS[k] for k in range(MAX_GOALS + 1)]


def _match_probs(lh: float, la: float) -> tuple[float, float, float, float]:
    """Return (p_home, p_draw, p_away, p_over25) for independent Poisson rates."""
    ph = _poisson_pmf(lh)
    pa = _poisson_pmf(la)
    p_h = p_d = p_a = p_o25 = 0.0
    for i in range(MAX_GOALS + 1):
        pi = ph[i]
        for j in range(MAX_GOALS + 1):
            p = pi * pa[j]
            if i > j:
                p_h += p
            elif i == j:
                p_d += p
            else:
                p_a += p
            if i + j > 2:
                p_o25 += p
    return p_h, p_d, p_a, p_o25


def _extract_anchor_probs(picks_list: list[dict]) -> tuple[float, float, float, float] | None:
    """Extract implied (p_home, p_draw, p_away, p_over25) from a match's picks list."""
    p_h = p_d = p_a = p_o25 = None
    for p in picks_list:
        lbl = (p.get("label") or "").strip()
        prob = p.get("prob")
        if prob is None or prob <= 0:
            continue
        low = lbl.lower()
        if low in ("1x2: home", "1x2: 1", "1x2 - home", "match result: home"):
            p_h = prob
        elif low in ("1x2: draw", "1x2: x", "1x2 - draw", "match result: draw"):
            p_d = prob
        elif low in ("1x2: away", "1x2: 2", "1x2 - away", "match result: away"):
            p_a = prob
        elif "over 2.5" in low and ("total" in low or "o/u" in low or low.startswith("over 2.5") or ": over 2.5" in low):
            if "1st" not in low and "2nd" not in low and "corner" not in low and "card" not in low and "booking" not in low:
                p_o25 = prob
        elif "under 2.5" in low and ("total" in low or "o/u" in low or low.startswith("under 2.5") or ": under 2.5" in low):
            if p_o25 is None and "1st" not in low and "2nd" not in low and "corner" not in low and "card" not in low:
                p_o25 = 1.0 - prob
    if p_h is None or p_d is None or p_a is None or p_o25 is None:
        return None
    s = p_h + p_d + p_a
    if s <= 0:
        return None
    return p_h / s, p_d / s, p_a / s, min(max(p_o25, 0.05), 0.95)


def fit_event(picks_list: list[dict]) -> dict | None:
    """Fit implied (lh, la) Poisson rates from a match's 1X2 + Over/Under 2.5 picks."""
    anchors = _extract_anchor_probs(picks_list)
    if anchors is None:
        return None
    th, td, ta, to25 = anchors

    def loss(lh: float, la: float) -> float:
        ph, pd, pa, po25 = _match_probs(lh, la)
        return (ph - th) ** 2 + (pd - td) ** 2 + (pa - ta) ** 2 + 1.5 * (po25 - to25) ** 2

    # Coarse grid search
    best_lh, best_la, best_err = 1.3, 1.1, 1e9
    for ih in range(2, 38, 2):
        lh = ih / 10.0
        for ia in range(2, 38, 2):
            la = ia / 10.0
            err = loss(lh, la)
            if err < best_err:
                best_lh, best_la, best_err = lh, la, err

    # Coordinate refinement
    for step in (0.1, 0.03, 0.01):
        improved = True
        while improved:
            improved = False
            for dlh, dla in ((step, 0), (-step, 0), (0, step), (0, -step)):
                nh = min(max(best_lh + dlh, 0.15), 4.5)
                na = min(max(best_la + dla, 0.15), 4.5)
                err = loss(nh, na)
                if err < best_err - 1e-9:
                    best_lh, best_la, best_err = nh, na, err
                    improved = True

    return {
        "lh": round(best_lh, 3),
        "la": round(best_la, 3),
        "total_xg": round(best_lh + best_la, 2),
        "fit_err": round(best_err, 5),
    }


_TOTAL_RE = re.compile(r"\b(over|under)\s+(\d+(?:\.\d+)?)\b", re.I)


def model_prob(fit: dict | None, label: str) -> float | None:
    """Compute the implied Poisson model probability for a standard goal/BTTS/1X2/DC pick label."""
    if not fit or not label:
        return None
    lh, la = fit["lh"], fit["la"]
    low = label.lower().strip()

    # Exclude half-time, corners, cards, player props
    if any(x in low for x in ("1st half", "2nd half", "half-time", "halftime", "ht/", "corner", "booking", "card", "shot", "foul", "offside", "player")):
        return None

    ph = _poisson_pmf(lh)
    pa = _poisson_pmf(la)

    # Total Goals Over/Under
    if "total" in low or "o/u" in low or low.startswith(("over ", "under ")) or ": over " in low or ": under " in low:
        m = _TOTAL_RE.search(low)
        if m:
            side, line = m.group(1).lower(), float(m.group(2))
            if line * 2 == int(line * 2):  # half or whole lines
                p_over = 0.0
                p_under = 0.0
                for i in range(MAX_GOALS + 1):
                    for j in range(MAX_GOALS + 1):
                        g = i + j
                        p = ph[i] * pa[j]
                        if g > line:
                            p_over += p
                        elif g < line:
                            p_under += p
                denom = p_over + p_under
                if denom > 0:
                    return (p_over / denom) if side == "over" else (p_under / denom)

    # BTTS / GG-NG
    if "both teams" in low or "btts" in low or "gg/ng" in low:
        p0h, p0a = ph[0], pa[0]
        p_gg = max(0.0, min(1.0, 1.0 - p0h - p0a + p0h * p0a))
        if low.endswith(("yes", "gg")) or ": yes" in low:
            return p_gg
        if low.endswith(("no", "ng")) or ": no" in low:
            return 1.0 - p_gg

    # 1X2 & Double Chance
    p_h, p_d, p_a, _ = _match_probs(lh, la)
    if low in ("1x2: home", "1x2: 1"):
        return p_h
    if low in ("1x2: draw", "1x2: x"):
        return p_d
    if low in ("1x2: away", "1x2: 2"):
        return p_a
    if "double chance" in low:
        if "1x" in low or "home or draw" in low:
            return p_h + p_d
        if "x2" in low or "draw or away" in low:
            return p_d + p_a
        if "12" in low or "home or away" in low:
            return p_h + p_a
    return None


def edge_vs_model(fit: dict | None, label: str, stated_prob: float | None) -> float | None:
    """Positive = model gives higher chance than SportyBet's stated_prob; negative = potential trap."""
    if stated_prob is None:
        return None
    mp = model_prob(fit, label)
    if mp is None:
        return None
    return round(mp - stated_prob, 4)
