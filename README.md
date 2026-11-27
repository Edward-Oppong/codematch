# CodeMatch

**Quantitative Sports Betting Intelligence & High-Frequency Accumulator Engineering Platform**

CodeMatch is an institutional-grade sports betting analytics and accumulator auditing engine. It reverses bookmaker overrounds, calculates exact multi-market joint probabilities, identifies toxic high-margin accumulator legs, and constructs mathematically optimal parlays and value singles using bookmaker pricing data.

Unlike conventional betting tools that offer ungrounded "tips", CodeMatch applies quantitative financial principles — **Kelly criterion bankroll management, closing line value (CLV) regression, combinatorial knapsack optimization, and time-staggered hedging** — to maximize expected return and minimize house drag.

The application never directly scrapes or attacks SportyBet servers. Data ingestion operates entirely client-side via a sandboxed, zero-dependency browser bookmarklet (**CodeMatch Bridge**) authenticated with constant-time secret tokens.

---

## Technical Stack & Architecture

- **Backend:** Python 3.12, Flask, Werkzeug, NumPy (vectorized odds & combinatorial searches).
- **Data Persistence:** SQLite3 with Write-Ahead Logging (`PRAGMA journal_mode=WAL`), memory temp stores, and sub-10ms query execution across 276 leagues.
- **Frontend:** Pure HTML5, Jinja2, Vanilla CSS3 (custom design system with light/night pitch dark mode, zero frontend frameworks or heavy dependencies).
- **Security:** Strict Host authorization (`ALLOWED_HOSTS`), DNS rebinding mitigation, origin validation, CSRF protections, and sandboxed client-side bridge.
- **Quality Assurance:** 100% test pass rate across 170 unit and integration tests (`pytest`).

### System Architecture Diagram

```mermaid
flowchart TD
    subgraph Client ["Client Browser Environment"]
        SB["SportyBet Web Platform"]
        BM["CodeMatch Bookmarklet (Bridge)"]
        SB -->|Extract DOM / Live Odds JSON| BM
    end

    subgraph Security ["Security & Verification Perimeter"]
        AUTH["Constant-time Token Validator"]
        REBIND["Host & DNS Rebinding Filter"]
        BM -->|HTTP POST with Secret Key| AUTH
        AUTH --> REBIND
    end

    subgraph Core ["CodeMatch Analytics Platform (Python 3.12 / Flask)"]
        INGEST["Bridge Ingestion API (/bridge)"]
        REBIND --> INGEST
        PARSER["Odds, Margin & Joint Probability Parser"]
        INGEST --> PARSER

        subgraph Engines ["Algorithmic Decision Engines"]
            PB["Parlay Suite: Knapsack Optimizer"]
            SURG["Batch Code Surgeon & Toxicity Grader"]
            VAL["Value Singles: Sharp Signal (Steam + Poisson + Cal + Kelly)"]
            CLV["CLV Tracker, Wilson Calibration & Rollover Ladder"]
        end

        PARSER --> Engines

        subgraph Storage ["Persistent Data Layer"]
            DB[("SQLite 3 (WAL Mode, Memory Temp Store)")]
        end

        Engines <--> DB
    end

    subgraph UI ["User Interface Layer (Vanilla HTML5 / CSS3 & Modern Sidebar)"]
        SIDEBAR["Persistent Sidebar Navigation (Hunt, Slip Lab, Games, Track, System)"]
        DOCK["Sticky Floating Booking Dock"]
        STEPPER["4-Step Betting Workflow"]
        QUEUE["1-Click Code Dispatcher"]
        Engines --> UI
        QUEUE -.->|Dispatch Optimized Slips| BM
    end
```

---

## Visual Design System & Quantitative Cues

CodeMatch relies on strict semantic colors to communicate quantitative reality to the bettor:

### 1. Acca Toxicity Color Matrix
Visualizes the compounded house cut ($1 - \prod(1 - m_i)$) extracted from accumulator slips:

| Grade | Compounded Margin | Visual Badge | Status Meaning |
|:---:|:---:|:---:|---|
| **Grade A** | $< 10\%$ | <kbd style="background:#e4f1e8;color:#276c44;padding:2px 8px;border-radius:12px;font-weight:bold;">Grade A</kbd> | **Elite / Ultra-Low Drag:** Compounded return $>90\%$. Institutional parlay standard. |
| **Grade B** | $10\% - 20\%$ | <kbd style="background:#eaf5ee;color:#2d8a56;padding:2px 8px;border-radius:12px;font-weight:bold;">Grade B</kbd> | **Moderate Drag:** Typical for 2–3 sharp selections. |
| **Grade C** | $20\% - 35\%$ | <kbd style="background:#fef7e8;color:#b57a1e;padding:2px 8px;border-radius:12px;font-weight:bold;">Grade C</kbd> | **High Drag:** Compounded house edge eats over a quarter of wager value. |
| **Grade D** | $35\% - 55\%$ | <kbd style="background:#fbeee9;color:#c24b2b;padding:2px 8px;border-radius:12px;font-weight:bold;">Grade D</kbd> | **Severe Drag:** Bookmaker keeps up to 55% of stake before matches kick off. |
| **Grade F** | $> 55\%$ | <kbd style="background:#f6e1dd;color:#a33a2b;padding:2px 8px;border-radius:12px;font-weight:bold;">Grade F</kbd> | **Toxic:** House extracts over half the ticket value. Actionable for Code Surgeon. |

### 2. Odds Zones & Risk Spectrum
Categorizes selections by bookmaker implied probability:

| Zone | Odds Range | Implied Chance | Color Code | Characteristics |
|---|:---:|:---:|:---:|---|
| **Very Short** | $< 1.10$ | $> 90.9\%$ | `Slate` | Heavy tail risk with minimal payout yield |
| **Lower Risk** | $1.10 - 1.49$ | $67.1\% - 90.9\%$ | `Emerald` | Double chance, heavy favorites, Over 1.5 Goals |
| **Medium** | $1.50 - 1.99$ | $50.3\% - 66.7\%$ | `Ochre` | Even-odds matchups, BTTS Yes/No, Draw No Bet |
| **Higher Risk** | $\ge 2.00$ | $< 50.0\%$ | `Crimson` | Underdogs, draws, high-variance proposition lines |

### 3. Visual Component Mockups

#### The Chance Hero (Code Audit Interface)
```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│  1 in 315                            ● ● ○ ○ ○ ○ ○ ○ ○ ○   Total Odds:       18.42     │
│  chance this code wins (0.32%)       ○ ○ ○ ○ ○ ○ ○ ○ ○ ○   Back per 1:       0.68      │
│                                      ○ ○ ○ ○ ○ ○ ○ ○ ○ ○   SportyBet keeps:  32%       │
│                                      ○ ○ ○ ○ ○ ○ ○ ○ ○ ○   Acca Toxicity:    Grade C   │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

#### Sticky Floating Booking Dock
```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│  📦 4 selections ticked  │  Total Odds: 4.85  │  Chance: 1 in 5 (20.6%)  │  [Make Code ⚡] │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Core Capabilities

### 1. Custom Parlay Generation Suite (`/leagues/parlay`)
Builds slips algorithmically using four distinct mathematical optimization strategies:
- **Target Odds Optimizer:** Dynamic knapsack algorithm that scans thousands of available market permutations across selected leagues to find the combination of legs that reaches an exact target multiplier (e.g. 3.0x, 10.0x) with the absolute highest joint probability $\prod P(\text{leg}_i)$.
- **Time-Staggered Hedging Engine:** Constructs chronological accumulator chains with guaranteed kickoff intervals ($\ge 90$ minutes). Because earlier games conclude before later ones start, users can lock in guaranteed risk-free profits via bookmaker early cash-out checkpoints.
- **Zone-Structured Portfolio Builder:** Allocates risk using institutional financial portfolio theory:
  - *Barbell Portfolio:* 80% high-probability anchors ($P > 0.82$) paired with 20% high-leverage multipliers.
  - *Core-Satellite System:* Conservative match selections balanced by targeted alternative lines.
- **Round-Robin & Systems Generator:** Automatic combinatorial expansion ($\binom{N}{2}, \binom{N}{3}$, etc.) into Doubles, Trebles, and Trixie covers, ensuring profit even if 1 or 2 legs fail.

### 2. Global Batch Code Surgeon & Multi-Code Audit (`/codes/batch-surgeon`)
Multi-leg accumulators rapidly compound the bookmaker's house edge ($1 - \prod (1 - m_i)$). A 10-leg slip where each leg carries an 8% margin surrenders **56.6%** of its stake to the house.
- **Toxicity Grading:** Scans all saved booking codes and grades them from **Grade A** (healthy, low margin) to **Grade F** (toxic, extreme negative expected return).
- **Automated Leg Curing:** Detects individual "toxic legs" (house margin $>9\%$ or win probability $<50\%$) and swaps them for safer, high-probability alternatives on the same match (e.g. replacing a high-variance Correct Score with Double Chance or Alternative Total) while maintaining code integrity.
- **Joint Probability Boost:** Computes before-and-after win probability increases and dispatches cured codes back to SportyBet in 1 click.

### 3. Value Singles Scanner (`/leagues/singles`)
The quantitative advantage alternative to high-margin accumulators. Finds single-match markets where bookmaker overround is minimal (highest expected return / back per 1 staked):
- Multi-factor sorting: **Highest Chance (most likely)**, **Smallest House Margin**, **Highest Odds**, and **Soonest Kick-off**.
- Advanced market filters: Handicap, Corners, Bookings, GG/NG, Halves, and Totals (with toggles to exclude extreme alternative unders).
- **Quarter-Kelly Staking:** Automatically calculates the mathematically optimal cash stake size for your bankroll:
  $$f^* = 0.25 \times \frac{b p - q}{b}$$

### 4. Closing Line Value (CLV) & Personal Calibration Engine (`/results/`)
- **Closing Line Value (CLV) Tracker:** Compares your placed odds against the bookmaker's closing price at kickoff. Consistently beating the closing line (+CLV) provides empirical proof of positive expectation independent of short-term variance.
- **Calibration Engine & Significance Gate:** Tests your empirical win rate against bookmaker probabilities across each market family with a 95% Wilson score confidence interval, applying a statistical threshold ($N \ge 50$) to prevent false precision.
- **Account Longevity Shield:** Suggests whole-number stake rounding and alerts against single-market over-concentration ($>60\%$) to evade bookmaker algorithmic profiling and account restrictions.

### 5. Automated Results & Predictions Settlement Hub (`/results/settlement`)
- **Scoreline Settlement Engine:** Ingests completed match scorelines and automatically determines winning/losing outcomes across all placed and saved bets.
- **Predictions vs. Reality Audit:** Compares empirical outcomes against SportyBet's implied chances across full-time 1X2, Over/Under lines, and Double Chance to verify bookmaker accuracy over time.
- **Manual Settlement Tools:** One-click settlement modal for non-score prop markets (Cards, Corners, Player props) where official automated feeds are unavailable.

### 6. Dedicated Community Code Hub Feed (`/codes/hub`)
- **Trending Slip Curation:** Displays public SportyBet booking codes filtered and ranked by community popularity, win probability, or expected return.
- **Toxicity Badges & Health Scoring:** Immediately flags community tickets carrying Grade D or Grade F house margins before betting.
- **Crowd Consensus Generator:** Synthesizes the most popular selections across all active community slips into an optimized consensus ticket, with **No Unders** and **Min Return** value filtering.
- **Combined Quantitative Signals (`Sharp Signal`):**
  - **Implied Poisson Goal Model (`app/analysis/poisson.py`):** Derives implied team expected goals ($\lambda_{\text{home}}, \lambda_{\text{away}}$) from SportyBet's own 1X2 and Over/Under 2.5 lines to flag model-backed picks and warn on traps without external APIs.
  - **Steam + Value Combo:** Badges and ranks picks where odds shortened since first import while retaining low house margin.
  - **Calibration-Adjusted Ranking:** Feeds settled market-family performance back into pick scoring.
- **Rollover Tracker (`/rollover`):** Step-by-step rolling bankroll ladder with live step projection, win/bust tracking, and direct links to `No Unders` Value Singles.

---

## Deployment & Setup

CodeMatch is designed to run seamlessly both **locally** (zero-config desktop tool) and in the **cloud** (Render, Docker, Railway).

### Local Execution (Desktop)

#### Windows
Double-click `start.bat`. On first launch, it automatically initializes the virtual environment, installs requirements, and launches your browser at `http://127.0.0.1:5000`.

#### Mac / Linux
```bash
chmod +x start.sh
./start.sh
```

#### Manual Setup
```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Mac / Linux:
source venv/bin/activate

pip install -r requirements.txt
python run.py
```
Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser. Run test suite: `pytest`.

---

### Cloud Deployment (Render.com)

CodeMatch includes native `render.yaml` configuration for 1-click cloud deployment:

1. Push your CodeMatch repository to **GitHub**.
2. Log into [Render.com](https://render.com) and click **New → Blueprint** (or **New Web Service**).
3. Connect your repository. Render automatically reads `render.yaml`:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn run:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
   - **Environment Variables:** `CODEMATCH_ALLOWED_HOSTS=*`, `PYTHON_VERSION=3.12.0`
4. Click **Deploy**. Your live CodeMatch web instance is accessible from anywhere.

#### Persistent Storage on Render
The SQLite database stores all imported matches, odds histories, and betting records in `./data/codematch.db`. For production deployments with persistent storage across container rebuilds:
- Attach a **Render Persistent Disk** mounted at `/var/data`
- Set environment variable: `CODEMATCH_DB=/var/data/codematch.db`

---

### Docker Deployment

A lightweight, multi-stage `Dockerfile` is included:

```bash
# Build Docker image
docker build -t codematch .

# Run container
docker run -d -p 5000:5000 -v $(pwd)/data:/app/data --name codematch codematch
```
Open [http://localhost:5000](http://localhost:5000).

---

**How the button reaches the app.** The bookmark asks the app on your computer (127.0.0.1) what to fetch and sends the
responses back. The app only accepts those calls from sportybet.com pages carrying its own secret key, which is built
into your bookmark; another website can't read from it or add to it. The first time, your browser may ask whether
sportybet.com may access devices on your local network: allow it. If the app moves to another port, drag the button
again from the Import page. When the bookmark's own code changes in an update, the app notices the old version
and asks you to drag the new one. (Version 3, for fetching Code Hub codes' games in the same trip, needs this once.)

The app only listens on this computer (127.0.0.1), only answers requests addressed to 127.0.0.1 or localhost (so a
website that points its own name at your computer, "DNS rebinding", is refused), rejects form posts the browser marks
as cross-site, keeps the bookmark's key out of the terminal log, and runs with debug mode off. Debug mode shows an error page that
lets whoever can see it run code on your machine, so turn it on only while developing (`CODEMATCH_DEBUG=1`); the app
refuses to start with debug mode on a non-local address. Change the address with `CODEMATCH_HOST` and the port with
`CODEMATCH_PORT`.


## Information Architecture & Dedicated Pages

The platform is organized around a persistent, responsive **Sidebar Navigation** with zero redundancy between features:

### 1. Hunt
- **⚡ Custom Parlay (`/leagues/parlay`):** Algorithmic accumulator builder across 4 strategies (Target Odds, Staggered Kickoff, Safe Zone, Round-Robin).
- **🎯 Value Singles (`/leagues/singles`):** Single-match +EV betting edge scanner with Quarter-Kelly cash staking recommendations.
- **🔍 Market Screener (`/leagues/?mode=screen`):** Multi-league scanner for finding games matching specific market criteria.
- **📉 Lowest Margins (`/leagues/margins`):** Direct ranking of leagues where bookmakers charge the lowest commission.
- **🏆 League Fixtures (`/leagues/`):** Clean directory of tournament fixtures and match odds.

### 2. Slip Lab
- **📋 Saved Codes (`/`):** Personal saved booking codes, toxicity checks, and 1-click surgeon curing.
- **🌐 Code Hub Feed (`/codes/hub`):** Dedicated community feed with trending codes, popularity sorting, toxicity grades, and crowd consensus slip builder.
- **🩺 Batch Surgeon (`/codes/batch-surgeon`):** Global multi-ticket curing engine to eliminate high-margin picks across multiple tickets simultaneously.
- **🔗 Shared Fixtures (`/codes/fixtures`):** Common-ground matches that appear across multiple codes.

### 3. Games & Steam
- **⚽ Match Directory (`/games/`):** Directory of imported fixtures with kick-off schedules.
- **📈 Odds Steam & Flow (`/games/steam`):** Real-time monitoring of shortening and drifting lines to detect smart-money flow.

### 4. Track & Settle
- **🏁 Predictions & Scores (`/results/settlement`):** Dedicated settlement hub for scoreline fetching, Predictions vs. Reality audits, and manual settlement.
- **💰 Bankroll & Kelly (`/results/`):** Dedicated bankroll ledger, P&L cashflow, Kelly stake sizing, monthly deposit limits, and Account Longevity Shield.

### 5. System
- **🔄 Sync & Bookmark (`/import/`):** Sandboxed browser bridge installation (with 400ms pause and pipelined async uploads for 4x faster fetching), HAR/JSON file import, and database maintenance.
- **📖 Master Guide (`/codes/guide`):** Complete mathematical and architectural reference manual.
Two legs on the same game are both kept, and their joint chance is worked out together rather than multiplied: exactly
when one implies the other, when they contradict, or when the combination is itself a priced market; otherwise it's
an estimate and the review says so.

**Fixtures across codes** (from the Codes page). Every game that appears in two or more saved codes, most shared
first: each pick the codes made on it, how many codes chose it, the odds each code had, its chance and return,
whether the codes contradict each other, the safest pick any code chose, and the common-ground pick (the
best-priced pick in the market that wins whenever the majority's picks win). It also builds a code from the
fixtures, optionally only those where the codes don't contradict each other: the safest or common-ground pick on
every fixture, or (the default) the highest chance for a total odds you choose, picked from what the codes chose,
optionally with at least a given number of legs. Picks on games not imported are marked "odds from code", with how
old those odds are.
"Make a SportyBet booking code" turns it into a real code with the CodeMatch button. 20 codes are compared in well
under a second.

**Leagues.** First fetch the league list (once), then tick the leagues you follow and press "Fetch the ticked leagues
with the CodeMatch button". The review shows one pick per game for the dates, markets (goals, bookings, corners) and
odds zone you choose; the row of league buttons above it narrows it to the leagues you tick. The right-hand columns
show what a code made of those picks would look like as legs are added. Set a **target** ("the code should win at
least 70% of the time") and it marks where to stop: the most likely picks are added until one more would take the
code below the target, with that code's chance, odds and return shown above the list.
Or set **total odds** ("highest chance for odds of at least 3"): out of every pick inside the filters, at most one
per game, it finds the code that reaches those odds and wins most often, next to what stacking the most likely
picks would give. The chance filter then works as a minimum for every leg.
**Choose the bet, find the teams** (the second tab on Leagues) works the other way round: tick the bets you want,
grouped as team goals, match goals, both teams to score, double chance, team corners, team bookings and other markets
(half-time, handicaps, combinations and the rest, from games fetched in full), and it lists every team or game that
offers them. Team bets merge SportyBet's home and away markets, so each row names the team, its opponent and whether
it plays at home. Filters: home or away teams only, an odds range, a minimum chance, one selection per match, and
leaving out selections that contradict another from the same match. The main tool is "find the highest-chance
selections for total odds of at least X with at most N selections": it shows the best code for each number of
selections, ranked by estimated chance, with a button to make any of them.
What the numbers are: *odds* are SportyBet's displayed odds; *chance* is the probability SportyBet sends with each of
its odds (its own estimate, margin taken out), shown only when that market's probabilities add up to a whole number
(1, or 2 for double chance), otherwise "not given" and never used in the search; *margin* is worked out from every
outcome of the whole market, and shown only when they are all on offer. A code's chance is an estimate that multiplies
the selections' chances, assuming the games don't affect each other; the search uses at most one selection per match,
because legs on the same match aren't independent. CodeMatch makes no predictions of its own.
**Where SportyBet keeps least** (linked from Leagues) shows the average margin for every kind of market and every
league over the saved games, split by odds zone, smallest first: where to look for picks that cost least.
You can now set a **Target Odds** directly on this page to automatically build an optimal booking slip composed
strictly of picks from these lowest-margin markets (&lt;10% cut), complete with live odds, combined chance, and
one-click SportyBet booking code generation.

**Value Singles Scanner** (the third tab on Leagues) is the quantitative advantage alternative to high-margin accumulators.
Instead of stacking legs that multiply the bookmaker's house edge, it scans across all saved matches to find the individual
selections where SportyBet takes the smallest margin (highest expected return / back per 1 staked). It displays the exact house
margin, expected return, and mathematical Quarter-Kelly stake recommendation for each pick, with one-click booking code generation.
**Making a booking code:** tick picks in that list (the ones inside your target come ticked) and press "Make a
SportyBet booking code from the ticked picks"; or, on a code's review, "Make a SportyBet booking code from this
version" after raising its chance. The CodeMatch button asks SportyBet to create the code and the new code is shown
in the app. Before making it, the same trip fetches each game in the code again, and the app then shows next to
the new code which picks' odds moved since you built it and which are no longer on offer (SportyBet may leave those
out). It only creates the code: checking it and deciding whether to stake stays with you, on SportyBet.

**Games.** The list can be narrowed by team and by league. Every market in one game, by family and zone. Click a pick to see the picks that do at least as well in
every result (safer) and those that win on only part of it (riskier), with the odds you give up or gain, plus the
pick's odds over time. The biggest odds moves since the first import are listed, and an "Other markets" tab shows
player and timing markets with their odds and chances (searchable by player).
**Odds Steam & Line Movement Tracker** (`/games/steam`) shows the picks that have moved most since first import:
direction (drifting out or steaming in), absolute and percentage move, and the full history of each pick. A "steam"
move — odds shortening sharply — signals that sharp money has moved the market. Drifting odds are a warning that
the bookmaker has repriced away from your code's assumption. Filter by direction (all / in / out) and minimum
percentage move.

**Results.** Record what you staked on a code (from its review or here). When a finished game is imported, its goal
legs settle on their own from the half-time and full-time score; bookings, corners and other markets are marked by
hand, on Results or right on the code's review, where each leg shows won, lost or void, with Undo for a hand-made
mark. Early-payout legs (1X2 2UP / 1UP) settle as won when their team wins and as lost when it never scored enough to
lead by the margin; otherwise they're marked by hand. The **Code Hub track record** counts every finished Code Hub
code, played or not, as if 1 had been staked on each: wins against what SportyBet's chances expect, for popular codes
(used by 5 or more) and the rest. It's kept after the codes are deleted, and reset with the bet record.
The page shows money in and out this month and in all, by month and by code size, a monthly limit you set
yourself (it warns, it doesn't block), and whether SportyBet's chances came true across all settled legs. The bet
record is kept even after deleting codes or clearing data.
**Bankroll Manager & Kelly Sizing.** Set your total betting fund (bankroll) and Kelly fraction (Quarter / Half / Full)
on the Results page. Once set, the app shows exact cash stake amounts on the Value Singles scanner and a Kelly stake
recommendation on each code review, based on the code's estimated edge and your bankroll. Quarter-Kelly is the default
(and safest) fraction — it limits drawdown while still following the optimal sizing signal.
**Closing Line Value (CLV) Tracker.** The Results page computes how your placed odds compare to the closing odds
SportyBet settled at (the last odds in the history before kick-off). Placing at higher odds than closing means you found
value before the market corrected — beating the closing line (+CLV) is the professional standard for proving positive
expected value over time. The tracker shows: bets analysed, how many beat the closing line, average weighted CLV %,
expected P&L (what your edge implied you should win), and realized P&L (what you actually won).
**Personal Calibration Engine & Significance Gate.** Overcomes the circular data trap (using SportyBet's probabilities to beat SportyBet)
by measuring your actual empirical win rate across settled legs by market family (1X2, Totals, BTTS, Corners, etc.).
Displays your empirical edge vs SportyBet's stated probability, a 95% Wilson score confidence interval, and statistical significance.
Until a sample reaches at least 50 bets in a market, the system warns against false precision.
**Accumulator Toxicity Scoring & Code Surgeon.** Evaluates multi-leg codes for compounded bookmaker margin (Grades A through F).
Calculates the exact break-even outperformance percentage required to overcome the house cut, and flags individual "toxic legs"
(market margin >9%) so you can trim or swap them.
**Account Longevity Shield.** Protects against bookmaker profiling and account restrictions: suggests rounded / jittered whole-number
stakes instead of telltale exact decimals, warns if your bet distribution becomes over-concentrated in a single market (>60%),
and alerts you to consider withdrawing profits when net return exceeds 50% of your starting bankroll.

**Choosing picks yourself.** Every list of picks has a box at the top of its first column that ticks the best pick
of every game in the list, and every recommended code (Leagues, the screener, Fixtures across codes, Best right now)
comes ticked so you can untick legs you don't want. A line under the list shows how many picks are ticked, their
total odds and chance, and updates as you tick. On Fixtures across codes, "Each fixture" lets you tick any pick any
code made, or start from the safest, most-chosen or common-ground pick on every fixture. Tick more than 50 picks (or
set "Picks per code") and they're made as several codes of near-equal size in one trip, up to 10 codes.
**Refreshing the league list.** "Refresh the league list from SportyBet" on Leagues fetches it again, so new
tournaments can be ticked; leagues that weren't there last time are marked new. "Find a league" filters the list.

## How picks are compared

Each result is described by four numbers: home and away goals (or bookings, or corners) in the first half and in the
second half. Full-time markets use the sums, half markets use one half, and markets like half-time/full-time use
both, so a first-half pick can be compared with a full-time one. Every pick wins, refunds or loses on each possible
result; pick A is "safer" than B when A does at least as well as B in every result.

Refund picks (draw no bet, home or away no bet, whole-number lines like Over 2 or Asian handicap -1) are handled
too. SportyBet's probability for these is the chance of winning if there's no refund; the app finds the refund
chance in the same game's prices (the draw, for draw no bet) and shows the chance of winning outright, the refund
chance, and a return that counts refunds.

Covered: results, double chance, no-bet markets, European and Asian handicaps, totals and team totals (half and
whole lines), exact goals, ranges, multigoals, goal bounds, excluded goals, odd/even, both teams to score, clean
sheets, win to nil, combos, correct scores and multiscores, "result or over/BTTS/clean sheet", and the first-half,
second-half and half-time/full-time versions of these; for bookings and corners the full-time and first-half
totals, team totals, results, handicaps, exact counts and ranges.
Also covered, each as its own family on a full-match and a first-half grid: shots, shots on target, fouls, offsides,
goal kicks, throw-ins, tackles, and posts and crossbars. On the Arsenal v Leeds test file that's 414 of 1,347 market
lines, every one consistent with SportyBet's own prices.
Early-payout 1X2 picks ("1X2 - 2UP", "1X2 - 1UP"), common in Code Hub codes, are paid as a win once the team leads by
2 (or 1) goals, however the game ends. The final score can't tell whether that happened, but it bounds it: the pick
surely wins when its team wins, and can win otherwise only if the team scored at least that many goals. The app keeps
both sets and every comparison respects them: "Home or Over 2.5" is safer than 2UP Home, while 1X2 Home is riskier.
"1X2 - Never Down" and "Early Goals" aren't modelled.
Not compared (listed under "Other markets" instead): player markets, timing and order markets (first goal, minute
ranges, "to lead at any time"), and booking points. Quarter lines (x.25, x.75) aren't modelled; SportyBet's data
didn't include any.

## Odds zones

| Zone | Odds | Typical picks |
|---|---|---|
| Very short | under 1.10 | near-certain in the bookmaker's view; pays almost nothing |
| Lower risk | 1.10 to 1.49 | double chance, big favourite to win, over 1.5, under 3.5, draw no bet on a favourite |
| Medium | 1.50 to 1.99 | win in an even game, both teams to score, over / under 2.5 |
| Higher risk | 2.00 and up | draw, correct score, over 3.5, underdog to win |

## Higher odds, same safety

For any pick, odds times chance is its return, and SportyBet keeps every return below 1. For legs on different games
the returns multiply, so

```
chance of the code = (product of the legs' returns) / total odds
```

At a given total odds, the chance depends only on how much margin the legs pile up. So the safest way to reach some
odds is few legs with small margins, and the costliest is many near-certain legs: on the Arsenal v Leeds prices, picks
under 1.05 give up almost as much in margin as they add in odds, while picks from 1.50 to 2.00 add about seven times
as much. That's what "highest chance for these odds" searches for (`analysis/target.py`). No pick is both long odds
and likely; this finds the best trade there is. Refund picks are left out of that search.

A zone describes how likely a pick is in the bookmaker's view, not whether it is good value. Every pick's
"return" (odds times probability) is below 1, because of the bookmaker's margin, and combining picks into one
code multiplies that margin: five lower-risk legs at 1.12 and 87% each give a code with about a 50% chance that
returns about 0.86 per 1 staked.

## Market Families & Non-Goal Markets

CodeMatch models and audits across all major SportyBet market families, not just match goals:
- **Handicap & Asian Handicap**: European 3-way handicap and 2-way Asian handicaps.
- **Corners**: Over/Under total corners, team corners, 1X2 corner winner, half-time corners.
- **Bookings & Cards**: Over/Under booking points and yellow/red cards, team bookings.
- **Both Teams to Score (GG/NG)**: Both teams to score Yes/No across full-time and halves.
- **Half-Time & Halves**: 1st/2nd half result, half-time totals, half-time/full-time combos.
- **Double Chance & Draw No Bet**: 1X, X2, 12, DNB, and early payout promo markets (1UP/2UP).
- **Match Stats**: Player fouls, offsides, shots on target, tackles, throw-ins.
- **Totals & Over/Under**: Full-time totals from 0.5 to 5.5+.

On the **Value Singles Scanner** (`/leagues/singles`), use the market family chips to filter singles by specific category (e.g. *Handicap*, *Corners*, *Bookings*, *GG/NG*). On **Where SportyBet Keeps Least** (`/leagues/margins`), build target odds accumulator slips optimized specifically within low-margin non-goal markets.

## Layout

Navigation, colours, type and page components are described in [DESIGN.md](DESIGN.md). Times are shown in UTC
(Ghana time) by default; the footer switch shows them in your device's time zone. The theme follows your device, or
can be pinned to light or dark with the button in the top bar.

```
start.bat / start.sh    one-click start (sets up on first run, opens the browser)
run.py                  starts the app
app/
  __init__.py           create_app(), template filters
  config.py             database path and upload limits
  db.py                 schema, upgrades from older databases
  store.py              saving and loading games, codes, price history, each game's priced picks
  sources/sportybet/    the only part that knows about SportyBet
    parse.py            reads its responses
    snippets.py         what each fetch asks SportyBet for: the console code and the CodeMatch button
    importer.py         uploads, pastes, HAR files
  analysis/             pure computation, independent of the source
    markets.py          which scorelines each pick wins on
    alternatives.py     safer and riskier picks
    picks.py            odds zones, one pick per game, accumulator maths
    codes.py            booking-code review, same-game legs, raising the chance
    settle.py           settling legs from final scores, money in and out, checking chances
    compare.py          code similarity and clusters
    consensus.py        fixtures shared across codes, common-ground picks
    target.py           the highest-chance code for a given total odds (and a maximum number of selections)
    bettypes.py         bet types for the screener, reliable chances, whole-market margins
  routes/               one file per section: codes, leagues, games, results, imports
                        bridge.py: the CodeMatch button's link to the app
  templates/            the pages
  static/css/           styles (light and dark)
tests/                  pytest suite, using a real Arsenal v Leeds response
scripts/analyse_game.py look at one saved game from the command line
data/                   the database (not committed)
```

To use a different odds source later, add a folder next to `sources/sportybet/` that produces the same game and
code data; nothing in `analysis/` or the pages needs to change.
