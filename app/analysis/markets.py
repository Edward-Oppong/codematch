"""Which results each pick wins on, refunds on, or loses on.

A match result is four numbers: home and away count in the first half, and home and away count in the second
half. Full-time markets use the sums, half markets use one half, and markets like half-time/full-time use both,
so every pick in a family (goals, bookings, corners) can be compared with every other.

Each pick becomes two sets of results, stored as bit masks over the grid of possible results:
  win  = results where the pick wins
  push = results where the stake is refunded (draw no bet on a draw, Over 2 with exactly 2 goals...)
Pick A is at least as safe as pick B when, in every possible result, A does no worse than B
(lose < refund < win).

Market ids are Sportradar's, which SportyBet uses. Another odds source would map its markets onto these.
"""
import re
from functools import lru_cache
from itertools import product

# Highest count per team per half on each family's grid. Full-time maxima are double these.
HALF_MAX = {"goals": 4, "bookings": 5, "corners": 8}
FAMILIES = {f: 2 * n for f, n in HALF_MAX.items()}          # kept for callers that list the families
_GRIDS = {f: list(product(range(n + 1), repeat=4)) for f, n in HALF_MAX.items()}   # (h1, a1, h2, a2)

SCOPE = {
    "ft": lambda c: (c[0] + c[2], c[1] + c[3]),
    "1h": lambda c: (c[0], c[1]),
    "2h": lambda c: (c[2], c[3]),
}


# ---------- two-number building blocks (home, away) ----------
RES = {"Home": lambda h, a: h > a, "Draw": lambda h, a: h == a, "Away": lambda h, a: h < a}
DC = {"Home/Draw": lambda h, a: h >= a, "Home/Away": lambda h, a: h != a, "Draw/Away": lambda h, a: h <= a,
      "Home or Draw": lambda h, a: h >= a, "Home or Away": lambda h, a: h != a, "Draw or Away": lambda h, a: h <= a}
BTTS = {"Yes": lambda h, a: h > 0 and a > 0, "No": lambda h, a: h == 0 or a == 0}
VALUE = {"total": lambda h, a: h + a, "home": lambda h, a: h, "away": lambda h, a: a}
OU = re.compile(r"^(Over|Under) (\d+(?:\.\d+)?)$")


def line_kind(x):
    """'half' for x.5, 'whole' for x.0, None for quarter lines (x.25, x.75), which aren't modelled."""
    twice = x * 2
    if abs(twice - round(twice)) > 1e-9:
        return None
    return "half" if round(twice) % 2 else "whole"


def ou_preds(text):
    """'Over 2.5' -> (win(n), push(n) or None) on a count n."""
    m = OU.match(text.strip())
    if not m:
        return None
    x = float(m.group(2))
    kind = line_kind(x)
    if kind is None:
        return None
    win = (lambda n: n > x) if m.group(1) == "Over" else (lambda n: n < x)
    return win, ((lambda n: n == x) if kind == "whole" else None)


def count_pred(text):
    """Count outcomes: '2', '3+', '1-2', '1-3+' (= 1 or more), 'No goal'."""
    t = text.strip()
    if t.lower() in ("no goal", "no goals"):
        return lambda n: n == 0
    m = re.fullmatch(r"(\d+)-(\d+)\+", t)
    if m:
        lo = int(m.group(1))
        return lambda n: n >= lo
    m = re.fullmatch(r"(\d+)-(\d+)", t)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return lambda n: lo <= n <= hi
    m = re.fullmatch(r"(\d+)\+", t)
    if m:
        lo = int(m.group(1))
        return lambda n: n >= lo
    if t.isdigit():
        k = int(t)
        return lambda n: n == k
    return None


def excluded_pred(text):
    """'Excluded number of goals': '2' wins unless exactly 2; '5+' wins on 0-4."""
    t = text.strip()
    m = re.fullmatch(r"(\d+)\+", t)
    if m:
        lo = int(m.group(1))
        return lambda n: n < lo
    if t.isdigit():
        k = int(t)
        return lambda n: n != k
    return None


def part2(text):
    """One part of a combo on a single scope: result, double chance, BTTS yes/no, or a half-line total."""
    t = text.strip()
    if t in RES:
        return RES[t]
    if t in DC:
        return DC[t]
    if t in BTTS:
        return BTTS[t]
    p = ou_preds(t)
    if p and p[1] is None:
        win = p[0]
        return lambda h, a: win(h + a)
    return None


def res_token(t, names):
    t = t.strip().lower()
    if t in ("home", "1"):
        return "home"
    if t in ("draw", "x"):
        return "draw"
    if t in ("away", "2"):
        return "away"
    if names:
        if t == (names[0] or "").lower():
            return "home"
        if t == (names[1] or "").lower():
            return "away"
    return None


def res_of(h, a):
    return "home" if h > a else ("away" if h < a else "draw")


def htft_pred(text, names):
    """'Home/Draw', 'draw/Arsenal' -> half-time result / full-time result."""
    parts = text.split("/")
    if len(parts) != 2:
        return None
    t1, t2 = res_token(parts[0], names), res_token(parts[1], names)
    if not t1 or not t2:
        return None
    return lambda c: res_of(*SCOPE["1h"](c)) == t1 and res_of(*SCOPE["ft"](c)) == t2


# ---------- handlers: (spec, outcome text, team names) -> (win(cell), push(cell) or None) ----------
def on(scope, f2):
    s = SCOPE[scope]
    return lambda c: f2(*s(c))


def h_table(scope, table):
    return lambda spec, d, names: (on(scope, table[d]), None) if d in table else None


def h_ou(scope, value):
    def h(spec, d, names):
        p = ou_preds(d)
        if not p:
            return None
        s, v, win, push = SCOPE[scope], VALUE[value], p[0], p[1]
        return (lambda c: win(v(*s(c)))), ((lambda c: push(v(*s(c)))) if push else None)
    return h


def h_count(scope, value, parser=count_pred):
    def h(spec, d, names):
        p = parser(d)
        if p is None:
            return None
        s, v = SCOPE[scope], VALUE[value]
        return (lambda c: p(v(*s(c)))), None
    return h


def h_oddeven(scope, value):
    def h(spec, d, names):
        if d not in ("Odd", "Even"):
            return None
        s, v, odd = SCOPE[scope], VALUE[value], d == "Odd"
        return (lambda c: (v(*s(c)) % 2 == 1) == odd), None
    return h


def h_yesno(f):
    """Yes/No market where f(cell) is the 'Yes' result."""
    def h(spec, d, names):
        if d == "Yes":
            return f, None
        if d == "No":
            return (lambda c: not f(c)), None
        return None
    return h


def h_yesno_spec(make):
    """Yes/No market whose condition depends on the specifier (e.g. total=1.5)."""
    def h(spec, d, names):
        f = make(spec)
        return h_yesno(f)(spec, d, names) if f else None
    return h


def h_handicap(scope):
    """Asian-style handicap: 'Home (-1.5)', 'Away (+1.0)', 'Home (0)', 'Away +0.5'. Whole lines refund on a tie."""
    def h(spec, d, names):
        m = re.match(r"^(Home|Away)\s*\(?([+-]?\d+(?:\.\d+)?)\)?$", d.strip())
        if not m:
            return None
        own = float(m.group(2))
        kind = line_kind(own)
        if kind is None:
            return None
        s = SCOPE[scope]
        diff = (lambda c: (lambda h_, a_: h_ - a_)(*s(c))) if m.group(1) == "Home" else \
               (lambda c: (lambda h_, a_: a_ - h_)(*s(c)))
        win = lambda c: diff(c) + own > 0
        push = (lambda c: diff(c) + own == 0) if kind == "whole" else None
        return win, push
    return h


def h_euro(scope):
    """European handicap 'Home (0:1)': add the handicap to the score, then 1X2."""
    def h(spec, d, names):
        m = re.match(r"^(Home|Draw|Away) \((\d+):(\d+)\)$", d.strip())
        if not m:
            return None
        side, hh, aa = m.group(1), int(m.group(2)), int(m.group(3))
        r = RES[side]
        return on(scope, lambda h_, a_: r(h_ + hh, a_ + aa)), None
    return h


def h_no_bet(scope, refund_on):
    """Draw no bet (refund on a draw), home no bet (refund on a home win), away no bet."""
    def h(spec, d, names):
        if d not in RES or d == refund_on:
            return None
        return on(scope, RES[d]), on(scope, RES[refund_on])
    return h


def h_score(scope):
    def h(spec, d, names):
        if spec and spec.startswith("score=") and spec != "score=0:0":
            return None                       # in-play correct score counts goals from now on
        m = re.match(r"^(\d+):(\d+)$", d.strip())
        if not m:
            return None
        hh, aa = int(m.group(1)), int(m.group(2))
        return on(scope, lambda h_, a_: (h_, a_) == (hh, aa)), None
    return h


def h_multiscores(spec, d, names):
    scores = {(int(a), int(b)) for a, b in re.findall(r"(\d+):(\d+)", d)}
    if not scores:
        return None
    return on("ft", lambda h_, a_: (h_, a_) in scores), None


def h_combo(*scopes):
    """'Home & Over 1.5' with each part on its own scope (e.g. full-time double chance & 1st-half BTTS)."""
    def h(spec, d, names):
        parts = d.split(" & ")
        if len(parts) != len(scopes) or len(parts) < 2:
            return None
        preds = [part2(p) for p in parts]
        if any(p is None for p in preds):
            return None
        fs = [on(s, p) for s, p in zip(scopes, preds)]
        return (lambda c: all(f(c) for f in fs)), None
    return h


def h_ft_combo(spec, d, names):
    return h_combo(*["ft"] * len(d.split(" & ")))(spec, d, names)


def h_htft(spec, d, names):
    p = htft_pred(d, names)
    return (p, None) if p else None


def h_htft_and(second):
    """'Home/Home & Under 1.5' (second = 'ft_total' or '1h_total') or 'Arsenal/Arsenal & 2' (second = 'ft_count')."""
    def h(spec, d, names):
        if " & " not in d:
            return None
        first, rest = d.rsplit(" & ", 1)
        p1 = htft_pred(first, names)
        if not p1:
            return None
        if second == "ft_count":
            p = count_pred(rest)
            if p is None:
                return None
            p2 = lambda c: p(sum(SCOPE["ft"](c)))
        else:
            q = ou_preds(rest)
            if not q or q[1] is not None:
                return None
            s = SCOPE["ft" if second == "ft_total" else "1h"]
            p2 = lambda c: q[0](sum(s(c)))
        return (lambda c: p1(c) and p2(c)), None
    return h


def h_htft_score(spec, d, names):
    m = re.match(r"^(\d+):(\d+) (\d+):(\d+)$", d.strip())
    if not m:
        return None
    ht, ft = (int(m.group(1)), int(m.group(2))), (int(m.group(3)), int(m.group(4)))
    return (lambda c: SCOPE["1h"](c) == ht and SCOPE["ft"](c) == ft), None


def h_highest_half(value):
    def h(spec, d, names):
        v = VALUE[value]
        first = lambda c: v(*SCOPE["1h"](c))
        second = lambda c: v(*SCOPE["2h"](c))
        f = {"1st half": lambda c: first(c) > second(c), "2nd half": lambda c: first(c) < second(c),
             "Equal": lambda c: first(c) == second(c)}.get(d.strip())
        return (f, None) if f else None
    return h


def h_half_btts(spec, d, names):
    parts = d.split("/")
    if len(parts) != 2 or any(p not in BTTS for p in parts):
        return None
    f1, f2 = on("1h", BTTS[parts[0]]), on("2h", BTTS[parts[1]])
    return (lambda c: f1(c) and f2(c)), None


def h_result_or(scope_a, scope_b):
    """'1st Half Result or Match Result': Home wins if either the half or the match ends Home."""
    def h(spec, d, names):
        if d not in RES:
            return None
        fa, fb = on(scope_a, RES[d]), on(scope_b, RES[d])
        return (lambda c: fa(c) or fb(c)), None
    return h


def _or_market(first, kind):
    """'Home Team or Over 2.5', 'Draw or GG', 'Away Team or Any Clean Sheet' (Yes/No)."""
    r = RES[first]
    if kind == "over" or kind == "under":
        def make(spec):
            try:
                x = float((spec or "").replace("total=", ""))
            except ValueError:
                return None
            if line_kind(x) != "half":
                return None
            t = (lambda h, a: h + a > x) if kind == "over" else (lambda h, a: h + a < x)
            return on("ft", lambda h, a: r(h, a) or t(h, a))
        return h_yesno_spec(make)
    if kind == "gg":
        return h_yesno(on("ft", lambda h, a: r(h, a) or (h > 0 and a > 0)))
    return h_yesno(on("ft", lambda h, a: r(h, a) or h == 0 or a == 0))     # any clean sheet


def _both_halves(kind):
    def make(spec):
        try:
            x = float((spec or "").replace("total=", ""))
        except ValueError:
            return None
        if line_kind(x) != "half":
            return None
        t = (lambda n: n > x) if kind == "over" else (lambda n: n < x)
        return lambda c: t(sum(SCOPE["1h"](c))) and t(sum(SCOPE["2h"](c)))
    return h_yesno_spec(make)


# ---------- the market table: id -> (family, label prefix, handler) ----------
G, B, C = "goals", "bookings", "corners"
MARKETS = {
    # full time, goals
    "1": (G, "1X2", h_table("ft", RES)),
    "10": (G, "Double Chance", h_table("ft", DC)),
    "11": (G, "Draw No Bet", h_no_bet("ft", "Draw")),
    "12": (G, "Home No Bet", h_no_bet("ft", "Home")),
    "13": (G, "Away No Bet", h_no_bet("ft", "Away")),
    "14": (G, "Handicap", h_euro("ft")),
    "15": (G, "Winning Margin", None),
    "16": (G, "Asian Handicap", h_handicap("ft")),
    "18": (G, "Total", h_ou("ft", "total")),
    "19": (G, "Home Total", h_ou("ft", "home")),
    "20": (G, "Away Total", h_ou("ft", "away")),
    "21": (G, "Exact Goals", h_count("ft", "total")),
    "23": (G, "Home Goals", h_count("ft", "home")),
    "24": (G, "Away Goals", h_count("ft", "away")),
    "25": (G, "Goal Range", h_count("ft", "total")),
    "26": (G, "Odd/Even", h_oddeven("ft", "total")),
    "27": (G, "Home Odd/Even", h_oddeven("ft", "home")),
    "28": (G, "Away Odd/Even", h_oddeven("ft", "away")),
    "29": (G, "BTTS", h_table("ft", BTTS)),
    "30": (G, "Teams to Score", h_table("ft", {
        "None": lambda h, a: h == 0 and a == 0, "Only Home": lambda h, a: h > 0 and a == 0,
        "Only Away": lambda h, a: h == 0 and a > 0, "Both teams": lambda h, a: h > 0 and a > 0})),
    "31": (G, "Home Clean Sheet", h_yesno(on("ft", lambda h, a: a == 0))),
    "32": (G, "Away Clean Sheet", h_yesno(on("ft", lambda h, a: h == 0))),
    "33": (G, "Home Win To Nil", h_yesno(on("ft", lambda h, a: h > a and a == 0))),
    "34": (G, "Away Win To Nil", h_yesno(on("ft", lambda h, a: a > h and h == 0))),
    "35": (G, "Combo", h_ft_combo), "36": (G, "Combo", h_ft_combo), "37": (G, "Combo", h_ft_combo),
    "546": (G, "Combo", h_ft_combo), "547": (G, "Combo", h_ft_combo),
    "41": (G, "Correct Score", h_score("ft")),
    "45": (G, "Correct Score", h_score("ft")),
    "548": (G, "Multigoals", h_count("ft", "total")),
    "549": (G, "Home Multigoals", h_count("ft", "home")),
    "550": (G, "Away Multigoals", h_count("ft", "away")),
    "551": (G, "Multiscores", h_multiscores),
    "450001": (G, "Goal Bounds", h_count("ft", "total")),
    "450002": (G, "Home Goal Bounds", h_count("ft", "home")),
    "450003": (G, "Away Goal Bounds", h_count("ft", "away")),
    "450004": (G, "Excluded Goals", h_count("ft", "total", excluded_pred)),
    "450005": (G, "Home Excluded Goals", h_count("ft", "home", excluded_pred)),
    "450006": (G, "Away Excluded Goals", h_count("ft", "away", excluded_pred)),
    "60000": (G, "Both Teams 2+", h_yesno(on("ft", lambda h, a: h >= 2 and a >= 2))),
    "900041": (G, "No Draw & BTTS", h_yesno(on("ft", lambda h, a: h != a and h > 0 and a > 0))),
    "854": (G, "Home or Over", _or_market("Home", "over")), "855": (G, "Home or Under", _or_market("Home", "under")),
    "856": (G, "Draw or Over", _or_market("Draw", "over")), "857": (G, "Draw or Under", _or_market("Draw", "under")),
    "858": (G, "Away or Over", _or_market("Away", "over")), "859": (G, "Away or Under", _or_market("Away", "under")),
    "860": (G, "Home or BTTS", _or_market("Home", "gg")), "861": (G, "Draw or BTTS", _or_market("Draw", "gg")),
    "862": (G, "Away or BTTS", _or_market("Away", "gg")),
    "863": (G, "Home or Any Clean Sheet", _or_market("Home", "cs")),
    "864": (G, "Draw or Any Clean Sheet", _or_market("Draw", "cs")),
    "865": (G, "Away or Any Clean Sheet", _or_market("Away", "cs")),
    # both halves together
    "47": (G, "HT/FT", h_htft),
    "46": (G, "HT/FT Correct Score", h_htft_score),
    "818": (G, "HT/FT & Total", h_htft_and("ft_total")),
    "819": (G, "HT/FT & 1H Total", h_htft_and("1h_total")),
    "820": (G, "HT/FT & Exact Goals", h_htft_and("ft_count")),
    "48": (G, "Home Win Both Halves", h_yesno(lambda c: c[0] > c[1] and c[2] > c[3])),
    "49": (G, "Away Win Both Halves", h_yesno(lambda c: c[0] < c[1] and c[2] < c[3])),
    "50": (G, "Home Win Either Half", h_yesno(lambda c: c[0] > c[1] or c[2] > c[3])),
    "51": (G, "Away Win Either Half", h_yesno(lambda c: c[0] < c[1] or c[2] < c[3])),
    "52": (G, "Highest Scoring Half", h_highest_half("total")),
    "53": (G, "Home Highest Scoring Half", h_highest_half("home")),
    "54": (G, "Away Highest Scoring Half", h_highest_half("away")),
    "55": (G, "1H/2H BTTS", h_half_btts),
    "56": (G, "Home Scores Both Halves", h_yesno(lambda c: c[0] > 0 and c[2] > 0)),
    "57": (G, "Away Scores Both Halves", h_yesno(lambda c: c[1] > 0 and c[3] > 0)),
    "58": (G, "Both Halves Over", _both_halves("over")),
    "59": (G, "Both Halves Under", _both_halves("under")),
    "900027": (G, "BTTS Both Halves", h_yesno(lambda c: all(c))),
    "540": (G, "Double Chance & 1H BTTS", h_combo("ft", "1h")),
    "541": (G, "Double Chance & 2H BTTS", h_combo("ft", "2h")),
    "1179": (G, "1H or Match Result", h_result_or("1h", "ft")),
}

# first half / second half versions of the single-half goal markets: (1st half id, 2nd half id, prefix, handler maker)
_HALVES = [
    ("60", "83", "1X2", lambda s: h_table(s, RES)),
    ("63", "85", "Double Chance", lambda s: h_table(s, DC)),
    ("64", "86", "Draw No Bet", lambda s: h_no_bet(s, "Draw")),
    ("65", "87", "Handicap", h_euro),
    ("66", "88", "Asian Handicap", h_handicap),
    ("68", "90", "Total", lambda s: h_ou(s, "total")),
    ("69", "91", "Home Total", lambda s: h_ou(s, "home")),
    ("70", "92", "Away Total", lambda s: h_ou(s, "away")),
    ("71", "93", "Exact Goals", lambda s: h_count(s, "total")),
    ("74", "94", "Odd/Even", lambda s: h_oddeven(s, "total")),
    ("75", "95", "BTTS", lambda s: h_table(s, BTTS)),
    ("76", "96", "Home Clean Sheet", lambda s: h_yesno(on(s, lambda h, a: a == 0))),
    ("77", "97", "Away Clean Sheet", lambda s: h_yesno(on(s, lambda h, a: h == 0))),
    ("78", "543", "1X2 & BTTS", lambda s: h_combo(s, s)),
    ("79", "544", "1X2 & Total", lambda s: h_combo(s, s)),
    ("542", "545", "Double Chance & BTTS", lambda s: h_combo(s, s)),
    ("900042", "900043", "Double Chance & Total", lambda s: h_combo(s, s)),
    ("81", "98", "Correct Score", h_score),
    ("552", "553", "Multigoals", lambda s: h_count(s, "total")),
    ("900036", "900038", "Home Win To Nil", lambda s: h_yesno(on(s, lambda h, a: h > a and a == 0))),
    ("900037", "900052", "Away Win To Nil", lambda s: h_yesno(on(s, lambda h, a: a > h and h == 0))),
    ("900032", "900029", "Home Odd/Even", lambda s: h_oddeven(s, "home")),
    ("900031", "900030", "Away Odd/Even", lambda s: h_oddeven(s, "away")),
    ("810001", None, "Goal Bounds", lambda s: h_count(s, "total")),
    ("810002", None, "Excluded Goals", lambda s: h_count(s, "total", excluded_pred)),
]
for _i1, _i2, _p, _mk in _HALVES:
    MARKETS[_i1] = (G, "1H " + _p, _mk("1h"))
    if _i2:
        MARKETS[_i2] = (G, "2H " + _p, _mk("2h"))


def _winning_margin(spec, d, names):
    t = d.strip()
    if t == "Draw":
        return on("ft", lambda h, a: h == a), None
    m = re.match(r"^(Home|Away) by (\d+)(\+?)$", t)
    if not m:
        return None
    k, plus = int(m.group(2)), m.group(3) == "+"
    sign = 1 if m.group(1) == "Home" else -1
    return on("ft", lambda h, a: (sign * (h - a) >= k) if plus else (sign * (h - a) == k)), None


MARKETS["15"] = (G, "Winning Margin", _winning_margin)

MARKETS.update({
    # bookings (yellow = 1, red = 2)
    "136": (B, "Bookings 1X2", h_table("ft", RES)),
    "139": (B, "Total Bookings", h_ou("ft", "total")),
    "900304": (B, "Home Bookings", h_ou("ft", "home")),
    "900305": (B, "Away Bookings", h_ou("ft", "away")),
    "900312": (B, "Bookings Handicap", h_handicap("ft")),
    "142": (B, "Exact Bookings", h_count("ft", "total")),
    "143": (B, "Home Exact Bookings", h_count("ft", "home")),
    "144": (B, "Away Exact Bookings", h_count("ft", "away")),
    "149": (B, "1H Bookings 1X2", h_table("1h", RES)),
    "152": (B, "1H Total Bookings", h_ou("1h", "total")),
    "900306": (B, "1H Home Bookings", h_ou("1h", "home")),
    "900307": (B, "1H Away Bookings", h_ou("1h", "away")),
    "155": (B, "1H Exact Bookings", h_count("1h", "total")),
    "156": (B, "1H Home Exact Bookings", h_count("1h", "home")),
    "157": (B, "1H Away Exact Bookings", h_count("1h", "away")),
    # corners
    "162": (C, "Corners 1X2", h_table("ft", RES)),
    "166": (C, "Total Corners", h_ou("ft", "total")),
    "900300": (C, "Home Corners", h_ou("ft", "home")),
    "900301": (C, "Away Corners", h_ou("ft", "away")),
    "165": (C, "Corner Handicap", h_handicap("ft")),
    "169": (C, "Corner Range", h_count("ft", "total")),
    "170": (C, "Home Corner Range", h_count("ft", "home")),
    "171": (C, "Away Corner Range", h_count("ft", "away")),
    "172": (C, "Corners Odd/Even", h_oddeven("ft", "total")),
    "173": (C, "1H Corners 1X2", h_table("1h", RES)),
    "177": (C, "1H Total Corners", h_ou("1h", "total")),
    "176": (C, "1H Corner Handicap", h_handicap("1h")),
    "900302": (C, "1H Home Corners", h_ou("1h", "home")),
    "900303": (C, "1H Away Corners", h_ou("1h", "away")),
    "180": (C, "1H Home Exact Corners", h_count("1h", "home")),
    "181": (C, "1H Away Exact Corners", h_count("1h", "away")),
    "182": (C, "1H Corner Range", h_count("1h", "total")),
    "183": (C, "1H Corners Odd/Even", h_oddeven("1h", "total")),
})

# ---------- other match stats ----------
# Shots, fouls, offsides... Their full-match and first-half markets are priced separately, so each is its own
# family on a plain (home count, away count) grid; "shots" and "shots, 1st half" are compared only within
# themselves. (family, highest count per team, full-match ids: (total, home, away, 1X2, handicap),
#  first-half ids: (total, home, away, 1X2))
STATS = [
    ("shots", 40, ("900394", "900552", "900553", "900320", None), (None, "900679", "900678", "900680")),
    ("shots on target", 20, ("900393", "900546", "900547", "900318", None), ("900550", "900654", "900655", "900652")),
    ("fouls", 30, ("900342", "900544", "900545", "900539", None), ("900541", "900686", "900687", "900647")),
    ("offsides", 12, ("900396", "900568", "900569", "900570", "900567"), ("900580", "900674", "900675", "900670")),
    ("goal kicks", 25, ("900622", "900623", "900624", "900629", None), ("900661", "900638", "900639", "900663")),
    ("throw-ins", 45, ("900769", "900778", "900779", "900780", None), ("900782", "900795", "900796", "900791")),
    ("tackles", 40, ("900614", "900615", "900616", None, None), (None, None, None, None)),
    ("posts and crossbars", 6, ("900617", "900619", "900620", "900618", None), ("900756", None, None, "900834")),
]
SCOPE["pair"] = lambda c: (c[0], c[1])
STAT_FAMILIES = {}
for _fam, _max, _ft, _h1 in STATS:
    for fam, ids, tag in ((_fam, _ft, ""), (_fam + ", 1st half", _h1, "1H ")):
        if not any(ids):
            continue
        STAT_FAMILIES[fam] = _max
        _GRIDS[fam] = list(product(range(_max + 1), repeat=2))
        name = _fam.capitalize()
        handlers = [(ids[0], f"{tag}Total {name}", h_ou("pair", "total")),
                    (ids[1], f"{tag}Home {name}", h_ou("pair", "home")),
                    (ids[2], f"{tag}Away {name}", h_ou("pair", "away")),
                    (ids[3], f"{tag}{name} 1X2", h_table("pair", RES))]
        if len(ids) > 4:
            handlers.append((ids[4], f"{tag}{name} Handicap", h_handicap("pair")))
        for mid, prefix, handler in handlers:
            if mid:
                MARKETS[mid] = (fam, prefix, handler)

MAIN_FAMILIES = list(HALF_MAX)                      # goals, bookings, corners
FAMILIES = {**FAMILIES, **STAT_FAMILIES}
FAMILY_IDS = {f: {k for k, v in MARKETS.items() if v[0] == f} for f in FAMILIES}
BOOKING_IDS = FAMILY_IDS[B]
CORNER_IDS = FAMILY_IDS[C]
_SPEC_IN_LABEL = {"58", "59", "854", "855", "856", "857", "858", "859"}   # outcome text doesn't carry the line


def classify_outcome(mid, spec, d, names=None):
    """(market id, specifier, outcome text) -> (family, label prefix, win(cell), push(cell) or None), or None
    when the market or outcome isn't modelled."""
    entry = MARKETS.get(mid)
    if not entry or entry[2] is None:
        return None
    family, prefix, handler = entry
    r = handler(spec or "", d or "", names)
    if not r or r[0] is None:
        return None
    if mid in _SPEC_IN_LABEL and spec:
        prefix = f"{prefix} {spec.split('=')[-1]}"
    return family, prefix, r[0], r[1]


def _generic(d, names):
    """Outcome text with team names replaced by Home / Away, so one cached result serves every game."""
    home, away = names
    if home and home in d:
        d = d.replace(home, "\x00H")
    if away and away in d:
        d = d.replace(away, "\x00A")
    return d.replace("\x00H", "Home").replace("\x00A", "Away")


def _masks(mid, spec, d, home="", away=""):
    return _masks_cached(mid, spec, _generic(d, (home, away)))


@lru_cache(maxsize=200_000)
def _masks_cached(mid, spec, d):
    c = classify_outcome(mid, spec, d, None)
    if not c:
        return None
    family, prefix, win, push = c
    w = p = 0
    for i, cell in enumerate(_GRIDS[family]):
        if win(cell):
            w |= 1 << i
        elif push is not None and push(cell):
            p |= 1 << i
    return family, prefix, w, p


def build_priced(event, family="goals"):
    """{label: pick} for every outcome we can model in one family. Each pick has odds, the bookmaker's
    probability, win / push masks, and 'ret' = average amount returned per 1 staked.

    For refund markets SportyBet's probability is the chance of winning when there is no refund. Where the
    game also prices the refund result on its own (the draw, for draw no bet), the chance of winning outright
    and the true return are worked out from it; otherwise the pick is flagged 'cond'."""
    names = (event.get("homeTeamName") or "", event.get("awayTeamName") or "")
    out = {}
    for m in event.get("markets") or []:
        mid, spec, desc = m["id"], m.get("specifier") or "", m.get("desc", "")
        for o in m.get("outcomes") or []:
            r = _masks(mid, spec, o.get("desc", ""), *names)
            if not r or r[0] != family:
                continue
            try:
                odds, prob = float(o["odds"]), float(o["probability"])
            except (KeyError, ValueError, TypeError):
                continue
            if o.get("isActive") != 1 or odds <= 1:
                continue
            out[f"{r[1]}: {o['desc']}"] = {"win": r[2], "push": r[3], "odds": odds, "prob": prob,
                                           "ret": odds * prob, "market": desc, "mid": mid, "spec": spec,
                                           "oid": o.get("id"), "family": family, "desc": o.get("desc", "")}
    _resolve_refunds(out)
    return out


def _resolve_refunds(priced):
    plain = {}
    for k, v in priced.items():
        if not v["push"] and v["win"] not in plain:
            plain[v["win"]] = (k, v["prob"])
    for v in priced.values():
        if not v["push"]:
            continue
        hit = plain.get(v["push"])
        if not hit:
            # the refund result isn't priced alone, but may be the difference of two picks
            # (exactly 3 first-half goals = 3 or more minus 4 or more)
            for wa, (ka, pa) in plain.items():
                if wa & v["push"] == v["push"] and (wa ^ v["push"]) in plain:
                    kb, pb = plain[wa ^ v["push"]]
                    if pa - pb > 0:
                        hit = (f"{ka.split(': ', 1)[0]}: exactly the line", pa - pb)
                        break
        v["prob_cond"] = v["prob"]
        if hit:
            label, p_push = hit
            v.update(prob=v["prob_cond"] * (1 - p_push), push_prob=p_push, refund_on=label,
                     ret=v["odds"] * v["prob_cond"] * (1 - p_push) + p_push)
        else:
            v.update(cond=True, push_prob=None, refund_on=None)


def priced_all(event, families=MAIN_FAMILIES):
    out = {}
    for f in families:
        out.update(build_priced(event, f))
    return out


# Early-payout 1X2 markets: the pick is paid as a win as soon as the team leads by this many goals, even if the
# game ends otherwise. The final score can't say whether that happened, but it bounds it: the pick surely wins when
# the team wins, and can only win otherwise if the team scored at least that many goals. So such a pick gets 'win'
# (results it surely wins on) and 'maybe' (results it may win on), and every comparison stays true either way.
EARLY_PAYOUT = {"60100": 2, "60200": 1}       # "1X2 - 2UP", "1X2 - 1UP"


def _early_masks(k, side):
    w = m = 0
    for i, (h1, a1, h2, a2) in enumerate(_GRIDS["goals"]):
        h, a = h1 + h2, a1 + a2
        if RES[side](h, a):
            w |= 1 << i
        elif side != "Draw" and (h if side == "Home" else a) >= k:
            m |= 1 << i
    return w, m


def early_info(mid, outcome_desc, names=("", "")):
    k = EARLY_PAYOUT.get(str(mid))
    side = (res_token(outcome_desc, names) or "").capitalize() if k else None
    if side not in RES:
        return None
    w, m = _early_masks(k, side)
    return {"family": "goals", "label": f"1X2 - {k}UP: {outcome_desc}", "win": w, "push": 0, "maybe": m,
            "early": k, "side": side}


def leg_info(mid, spec, outcome_desc, names=None):
    """Turn one booking-code leg into its masks (no odds needed), or None if we can't model it."""
    names = names or ("", "")
    r = _masks(mid, spec or "", outcome_desc, names[0] or "", names[1] or "")
    if not r:
        return early_info(mid, outcome_desc, names)
    return {"family": r[0], "label": f"{r[1]}: {outcome_desc}", "win": r[2], "push": r[3]}


def covers(a, b):
    """True when a does at least as well as b in every possible result (lose < refund < win). An early-payout pick
    counts only its sure wins when it is a, and every result it may win on when it is b."""
    aw, bw = a["win"], b["win"] | b.get("maybe", 0)
    return (bw & ~aw) == 0 and ((bw | b["push"]) & ~(aw | a["push"])) == 0


def relation(a, b):
    """How two picks on the SAME game relate. 'x_covers_y' = x does at least as well whenever y wins."""
    if a is None or b is None or a["family"] != b["family"]:
        return "unrelated"
    if a["win"] == b["win"] and a["push"] == b["push"] and a.get("maybe", 0) == b.get("maybe", 0):
        return "same"
    if covers(b, a):
        return "b_covers_a"
    if covers(a, b):
        return "a_covers_b"
    reach = lambda x: x["win"] | x["push"] | x.get("maybe", 0)
    return "conflict" if not (reach(a) & reach(b)) else "overlap"


def families_present(event):
    """Which families this game's imported markets cover."""
    ids = {m.get("id") for m in event.get("markets") or []}
    return {f: bool(ids & FAMILY_IDS[f]) for f in FAMILIES}


def other_markets(event):
    """Markets in the game that aren't modelled (players, timing, booking points...), with each outcome's odds,
    SportyBet's chance and odds x chance. They can't be compared with other picks, but they can be looked at."""
    names = (event.get("homeTeamName") or "", event.get("awayTeamName") or "")
    out = []
    for m in event.get("markets") or []:
        outs = m.get("outcomes") or []
        if any(_masks(m["id"], m.get("specifier") or "", o.get("desc", ""), *names) for o in outs):
            continue
        rows = []
        for o in outs:
            try:
                odds, prob = float(o["odds"]), float(o["probability"])
            except (KeyError, ValueError, TypeError):
                continue
            if o.get("isActive") == 1 and odds > 1:
                rows.append({"desc": o.get("desc", ""), "odds": odds, "prob": prob, "ret": odds * prob})
        if rows:
            out.append({"market": m.get("desc", ""), "group": _group(m.get("desc", ""), m["id"]), "outcomes": rows})
    return out


def _group(desc, mid):
    d = desc.lower()
    if any(k in d for k in ("player", "scorer", "most ", "goalscorer", "assist", "shots by")):
        return "Players"
    if any(k in d for k in ("goalkeeper", "keeper", "save")):
        return "Goalkeepers & Saves"
    timing = ("minute", "1st ", "first", "last", "lead", "behind", "1up", "2up", "never down", "early", "in a row",
              "when will", "1 to ")
    if any(t in d for t in timing):
        return "Timing and order"
    return "Other"
