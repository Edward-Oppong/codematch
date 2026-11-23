"""Bet types for the screener: "choose the bet, find the teams".

Every saved pick gets a bet-type key that is the same across games, so one bet type (say "a team scores over 0.5")
can be looked up in every game at once. For team bets, SportyBet's separate home and away markets ("Home Total",
"Away Total") become one bet type, and each pick remembers which side it is for.

Also here: which of SportyBet's probabilities can be relied on, and the margin of a whole market. SportyBet sends a
probability with every outcome. Within a market whose outcomes cover every result exactly once, those probabilities
add up to 1 (to 2 for double chance, where every result is covered twice), and the margin follows from the odds:

    SportyBet keeps = 1 - k / sum(1 / odds)          k = what the probabilities add up to (1 or 2)

When a market's probabilities don't add up to a whole number (outcomes that overlap unevenly, or a market listing
only some results) its figures aren't treated as reliable, and no margin is shown.
"""
import re

CATS = [
    ("team_goals", "Team goals"),
    ("match_goals", "Match goals"),
    ("btts", "Both teams to score"),
    ("dc", "Double chance"),
    ("team_corners", "Team corners"),
    ("team_bookings", "Team bookings"),
    ("other", "Other markets"),
]
CAT_LABEL = dict(CATS)
TEAM_CATS = {"team_goals", "team_corners", "team_bookings"}
_SIDE = re.compile(r"\b(Home|Away)\b")
_OU = re.compile(r"^(Over|Under) (\d+(?:\.\d+)?)$")
DC_NAMES = {"Home or Draw": "1X (home or draw)", "Draw or Away": "X2 (draw or away)", "Home or Away": "12 (home or away)"}


def _named(text, home, away):
    """Team names in a label become Home / Away, so the label means the same thing in every game."""
    for name, word in ((home, "Home"), (away, "Away")):
        if name and len(name) > 2 and name in text:
            text = text.replace(name, word)
    return text


def classify(label, home="", away=""):
    """(category, key, side, name) for one saved pick label such as 'Away Total: Over 0.5'.
    side is 'home' or 'away' for a bet on one team, else None. name is how the bet type is shown."""
    prefix, _, pick = _named(label, home, away).partition(": ")
    if prefix == "Double Chance":
        return "dc", f"dc|{pick}", None, DC_NAMES.get(pick, pick)
    if prefix == "Total" and _OU.match(pick):
        return "match_goals", f"match_goals|{pick}", None, f"{pick} goal{'' if pick.endswith(' 1') else 's'}"
    if prefix == "BTTS":
        return "btts", f"btts|{pick}", None, f"Both teams score: {pick}"
    sides = set(_SIDE.findall(f"{prefix} {pick}"))
    side = sides.pop().lower() if len(sides) == 1 else None
    if side:
        g_prefix, g_pick = _SIDE.sub("Team", prefix), _SIDE.sub("Team", pick)
    else:
        g_prefix, g_pick = prefix, pick
    team = {"Team Total": ("team_goals", "Team"), "Team Corners": ("team_corners", "Team corners"),
            "Team Bookings": ("team_bookings", "Team bookings")}
    if side and g_prefix in team and _OU.match(pick):
        cat, word = team[g_prefix]
        return cat, f"{cat}|{pick}", side, f"{word} {pick[0].lower()}{pick[1:]}"
    return "other", f"other|{g_prefix}: {g_pick}", side, f"{g_prefix}: {g_pick}"


def sort_key(key):
    """Bet types in a sensible order: Over before Under, lines low to high, then by name."""
    cat, _, rest = key.partition("|")
    m = _OU.match(rest)
    if m:
        return (0, m.group(1) != "Over", float(m.group(2)), rest)
    return (1, 0, 0.0, rest)


def market_checks(event):
    """{(market id, specifier): (probabilities reliable, SportyBet keeps or None)} for every market in a game."""
    out = {}
    for m in event.get("markets") or []:
        outs = m.get("outcomes") or []
        key = (m.get("id"), m.get("specifier") or "")
        try:
            probs = [float(o["probability"]) for o in outs]
            odds = [float(o["odds"]) for o in outs]
        except (KeyError, TypeError, ValueError):
            out[key] = (False, None)
            continue
        total = sum(probs)
        k = round(total)
        reliable = bool(outs) and k in (1, 2) and abs(total - k) <= 0.01 and all(0 <= p <= 1 for p in probs)
        kept = None
        if reliable and all(o.get("isActive") == 1 for o in outs) and all(x > 1 for x in odds):
            kept = 1 - k / sum(1 / x for x in odds)
        out[key] = (reliable, kept)
    return out
