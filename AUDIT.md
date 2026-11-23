# Audit, October 2026

What was checked, what was found and fixed, and what is still open. The checks live on as tests
(`tests/test_audit.py`, `tests/test_security.py`); put real SportyBet exports in `tests/fixtures/real/` and the
market checks run on every game in them.

## Security

| Check | Result |
|---|---|
| DNS rebinding: a website points its own name at 127.0.0.1 and talks to the app as its own page | **Was open.** The "same site" check compared the Origin with the Host, both chosen by that website, and page views weren't checked at all, so such a site could read saved codes and bets and press delete. **Fixed:** the app only answers requests addressed to 127.0.0.1, localhost or [::1] (plus `CODEMATCH_HOST` if set). |
| Cross-site form posts | Origin/Referer check was in place; posts with neither header were accepted. **Added:** posts the browser marks `Sec-Fetch-Site: cross-site` are refused. |
| Bookmark key | Compared in constant time; only sportybet.com origins; only sportybet.com URLs can be queued. **Found:** the key was printed in the terminal on every bridge call. **Fixed:** shown as `k=(hidden)`. Still true by design: SportyBet's own page scripts can see the key while the bookmark runs (they could post fake data or read the current job, not queue fetches or touch other data). "Make a new key" on Import retires it. |
| SQL | Every SQL string built in code only inserts constants or `?` placeholders. No user input reaches SQL text. |
| HTML / JSON in pages | Jinja escapes everything; `tojson` escapes quotes and `<>&` in attributes; the only `innerHTML` uses are server-rendered (escaped) HTML or text passed through an escape function. |

## Maths, checked against SportyBet's own prices (Arsenal v Leeds)

| Claim | How it was checked | Result |
|---|---|---|
| SportyBet's probability is its own estimate with the margin taken out | Sums per market: probabilities 1.000 (median of 1,342 markets), 1/odds 1.05 | Holds for markets covering each result once |
| Draw no bet: SportyBet's figure is the chance given no draw | Against 1X2: 0.8545 vs 0.8545 | Exact |
| Whole-number lines (Over 2, Asian handicaps): chance given no refund | Over 2: 0.6890 vs P(3+)/(1 - P(2)) = 0.6892 | Exact to 0.0002 |
| The app's outright and refund chances for those picks | Over 2: outright 0.5245 = P(3+), refund 0.2389 = P(exactly 2) | Exact |
| The market model reads every full-time goals pick correctly | For 346 picks: SportyBet's probability must lie between the correct-score probabilities summed over the scores where the app says the pick wins, with SportyBet's "other" scores (6% of the probability) counted as all losing or all winning | All 346 inside |
| The same for picks that depend on the halves | 796 picks against the half-time/full-time correct score ("other" is 30% there, so this only catches gross errors) | All inside |
| Double chance probabilities add up to 2, margin uses k = 2 | Sum 2.000; each within 0.002 of the 1X2 sums | Holds (small cross-market inconsistency, up to 0.2 points) |
| Margin is spread evenly across a market | Per-outcome margin (1 - odds x chance) within complete markets | **Does not hold.** 1X2: 1.3% on the favourite to 3.7% on the outsider; rare outcomes up to 90%+. So the whole-market margin is an average, and a pick can cost much more. The screener now labels it "Market margin" and shows each pick's own "back per 1" next to it, with a note. |

## Bugs found and fixed

1. **Running "back per 1" on Leagues ignored refunds.** For draw no bet plus Over 2 it showed 0.568 instead of
   0.941 (it multiplied odds by the chance of winning outright). Now the product of each pick's return, refunds
   included.
2. **The "did SportyBet's chances come true" check counted a pick once per code.** A pick in 27 codes counted as 27
   results. Now each pick counts once.
3. **A code's average return for two refund legs on the same game** (an estimate) ignored the refunds. Now the
   legs' returns multiply, consistent with the estimate.

Each has a test that fails on the old code.

## Checked and correct

- Settlement: a void leg counts as odds 1; a code loses as soon as one leg loses; whole lines void on the line.
- The calibration check compares won / (won + lost) with SportyBet's figure; for refund picks that figure is the
  chance given no refund, which is exactly what won / (won + lost) measures.
- Same-game joint chance: exact when one leg implies the others (the narrower leg's chance), when they contradict
  (0), or when the intersection is itself a priced pick; otherwise a labelled estimate.
- Target-odds search: tested against brute force (any number of picks, and a maximum number), with and without numpy.

## Still open

- **One real match.** Every check above ran on one game from one league. The tests are ready for more: export 5 to
  10 games from different leagues (fetched in full), one league fetch, one finished game and one game with
  suspended markets into `tests/fixtures/real/`.
- **Suspended picks** are assumed to come back with `isActive` not 1 when a game is fetched again (the "no longer on
  offer" message depends on it). Unconfirmed until a real game with suspended markets is exported.
- **The chance a code "wins"** counts outright wins only; with refund legs the code also pays (less) on a refund.
  Pages say so, but the Leagues target chance is therefore a little conservative.
- **The half-dependent model check** is loose (30% of the probability is on unlisted scores).
- **Code Hub paging.** The list request carries `"i": 0`; the app takes it as the page number and asks for
  `i = 0, 1, 2...`. Unconfirmed: if repeated pages come back identical, the import says "(0 new)" for them.
- **Code Hub orderType 4** codes are left out: their listed total isn't the product of their legs' odds, so they
  aren't plain accumulators. What they are (system bets?) is unconfirmed.
- **Early-payout markets.** "1X2 - 2UP" and "1UP" are now modelled by bounds (sure wins: the team wins; possible
  wins: also when it scored at least 2 or 1), so comparisons, contradictions and settlement stay correct; settlement is
  by hand only when the score can't decide. Unconfirmed: that SportyBet settles them on the first 90 minutes like
  plain 1X2. "Never Down" and "Early Goals" are still not modelled.
- **The bundled league names** are Sportradar tournament ids as commonly used (17 Premier League, 8 LaLiga, 21 EFL Cup,
  217 DFB Pokal and so on). The league list from SportyBet overrides them when fetched.

## Verification & Quantitative Engine Audit (November 2026)

| Component | Mathematical / Technical Basis | Test Verification |
|---|---|---|
| **Custom Parlay Builder Suite** | • Target Odds: dynamic programming & greedy knapsack maximizing $\prod P(leg)$<br>• Time-Staggered: chronological kickoff intervals $\ge 90$ mins ensuring cashout hedging<br>• Zone Portfolio: Barbell (80% banker / 20% value) & Core-Satellite risk allocations<br>• Round-Robin: exact permutation combinatorics $\binom{N}{k}$ for partial cover | `tests/test_parlay_builder.py` (all tests passing) |
| **Batch Code Surgeon & Audit** | • Compounded margin drag formula: $1 - \prod (1 - m_i)$<br>• Toxicity scoring: identifying individual legs where house edge $> 9\%$ or win prob $< 50\%$<br>• Automated leg replacement: finds safest equivalent market on same match with minimal margin drag | `tests/test_batch_surgeon.py` (all tests passing) |
| **Value Singles Scanner** | • Expected return ranking: $E[R] = \text{odds} \times P(\text{win}) + 1.0 \times P(\text{refund})$<br>• Quarter-Kelly bankroll sizing: $f^* = 0.25 \times \frac{b p - q}{b}$ avoiding aggressive drawdown<br>• Multi-market coverage: Handicap, Corners, Bookings, GG/NG, Halves, Totals | `tests/test_value_singles.py`, `tests/test_bankroll.py` |
| **Closing Line Value (CLV)** | • Logarithmic and percentage edge vs bookmaker closing price: $\text{CLV} = \frac{\text{odds}_{\text{placed}}}{\text{odds}_{\text{closing}}} - 1$<br>• Empirical proof of positive expectation independent of short-term variance | `tests/test_bankroll.py` |
| **Personal Calibration Engine** | • 95% Wilson score confidence interval around empirical win rate<br>• Minimum sample threshold ($N \ge 50$) preventing false precision | `tests/test_bankroll.py` |
| **Full Test Suite Status** | 168 automated tests covering parsing, security, quantitative math, database transactions, and UI workflows | **168 passed in 222s (100% pass rate)** |
