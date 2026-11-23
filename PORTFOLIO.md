# CodeMatch · Engineering & Quantitative Portfolio Showcase

> **One-Line Summary:** An institutional-grade quantitative sports betting analytics engine and accumulator optimization platform that reverse-engineers bookmaker margins, models joint probabilities across correlated markets, and algorithmically constructs mathematically optimal betting portfolios.

---

## Resume / CV Bullet Points (Ready to Use)

- **Engineered an institutional-grade quantitative betting platform** in Python 3.12, Flask, SQLite (WAL mode), and NumPy, auditing accumulator booking codes and computing exact multi-market joint probabilities across 270+ worldwide leagues.
- **Formulated a combinatorial knapsack optimization engine** (`parlay_builder.py`) using dynamic programming to construct accumulator slips maximizing joint probability $\prod P(\text{leg}_i)$ for exact target payout multipliers (e.g., 2.0x–50.0x) in $<10\text{ms}$.
- **Developed automated "Code Surgeon" and Toxicity Scoring algorithm** detecting compounded bookmaker overround ($1 - \prod(1 - m_i)$) and swapping high-drag selections for safer, higher-probability market equivalents on the same fixture.
- **Implemented risk-management algorithms** including Quarter-Kelly Criterion optimal stake sizing, Closing Line Value (CLV) regression tracking, 95% Wilson-score calibration confidence intervals, and time-staggered hedging schedules.
- **Architected a zero-attack-surface client-side scraping pipeline** via an authenticated browser bookmarklet (CodeMatch Bridge) utilizing constant-time token verification, DNS rebinding mitigation, and strict SameSite/CORS origin controls.
- **Achieved 100% test pass rate across 168 automated unit and integration tests** with continuous verification, zero external npm dependencies, and single-click containerized deployment on Render and Docker.

---

## Quantitative & Mathematical Foundations

### 1. Compounded House Margin (Accumulator Drag)
Bookmakers apply an overround $m$ to each market. In an accumulator of $N$ legs, the true expected return diminishes exponentially:
$$E[R_{\text{parlay}}] = \prod_{i=1}^{N} (1 - m_i)$$
A standard 10-leg accumulator with an 8% margin per leg retains only:
$$(1 - 0.08)^{10} = 0.92^{10} \approx 43.4\% \implies \mathbf{56.6\% \text{ loss to house margin}}$$
CodeMatch calculates this exact drag and ranks slips by expected return ($E[R]$) rather than misleading nominal odds.

### 2. Target Odds Optimization (Knapsack Variant)
Given a match pool $\mathcal{M}$ and candidate market selections $\mathcal{C}_j$ for each match, the engine solves:
$$\max \prod_{j \in \mathcal{S}} P(c_j) \quad \text{subject to} \quad \prod_{j \in \mathcal{S}} \text{Odds}(c_j) \ge T, \quad |\mathcal{S} \cap \text{Match}_k| \le 1$$
Where $T$ is the target odds threshold. NumPy vectorization enables sub-10ms combinatorial search across thousands of permutations.

### 3. Quarter-Kelly Stake Sizing
To prevent Gambler's Ruin while capitalizing on positive edge ($b p - q > 0$):
$$f^* = 0.25 \times \frac{b \cdot p - (1 - p)}{b}$$
Where $b = \text{odds} - 1$, $p = \text{probability}$, and the 0.25 dampening factor restricts drawdown to acceptable risk tolerances.

### 4. Closing Line Value (CLV) & Expected Value Proof
$$\text{CLV} = \frac{\text{Odds}_{\text{placed}}}{\text{Odds}_{\text{closing}}} - 1$$
By archiving the odds movement timeline up to kickoff, CodeMatch provides empirical proof that a bettor's strategy yields positive expected value (+EV) regardless of short-term variance.

---

## System Architecture

```mermaid
flowchart TD
    subgraph Client ["Client Browser (SportyBet Environment)"]
        SB["SportyBet Live Session"]
        BM["CodeMatch Bookmarklet (Bridge)"]
        SB -->|DOM / JSON Payload| BM
    end

    subgraph Security ["Security & Verification Gate"]
        AUTH["Constant-time Token Check"]
        ORIGIN["Origin & DNS Rebinding Filter"]
        BM -->|Local Post with Secret Key| AUTH
        AUTH --> ORIGIN
    end

    subgraph Core ["CodeMatch Core Server (Flask & Python 3.12)"]
        API["Bridge & Ingestion Routes"]
        ORIGIN --> API
        PARSER["Market & Probability Parser"]
        API --> PARSER
        
        subgraph Engine ["Quantitative Analytics Engine"]
            PB["Custom Parlay Builder (Knapsack / Staggered / Barbell)"]
            SURG["Batch Code Surgeon & Toxicity Grader"]
            VAL["Value Singles Scanner (Quarter-Kelly)"]
            CLV["CLV Tracker & Wilson Calibration"]
        end
        
        PARSER --> Engine
        
        subgraph Storage ["High-Performance Storage"]
            DB[("SQLite 3 (WAL Mode, Memory Temp Store)")]
        end
        
        Engine <--> DB
    end

    subgraph UI ["User Interface (Jinja2 & Custom CSS System)"]
        DOCK["Sticky Floating Booking Dock"]
        STEPPER["4-Step Betting Pipeline"]
        DISPATCH["1-Click Code Dispatcher"]
        Engine --> UI
        DISPATCH -.->|Queue Booking Order| BM
    end
```

---

## Technical Highlights for Recruiters & Hiring Managers

| Category | Implementation Details |
|---|---|
| **Language & Frameworks** | Python 3.12, Flask, Werkzeug, NumPy |
| **Database Engineering** | SQLite3 configured with WAL mode (`PRAGMA journal_mode=WAL`), 30-second busy timeout, 256MB memory mapping (`mmap_size`), and indexed composite lookups (`picks(event_id, family)`). |
| **Algorithms** | Dynamic Programming knapsack solver, chronological interval scheduling, combinatorial permutation generating ($\binom{N}{k}$), Wilson score confidence interval calculation. |
| **Frontend Architecture** | Zero npm dependencies, 100% vanilla CSS custom tokens, system dark mode support (`color-scheme: dark`), responsive fluid layout, floating action dock. |
| **Security Engineering** | Mitigated DNS rebinding, enforced strict Origin / Referer validation, constant-time authentication tokens, cross-site fetch refusal (`Sec-Fetch-Site`). |
| **DevOps & Cloud** | Ready for 1-click cloud deployment via `render.yaml`, multi-stage Docker containerization (`Dockerfile`), Windows batch launcher (`start.bat`), Unix shell script (`start.sh`). |
| **Testing & Reliability** | 168 automated tests using `pytest`, testing against real-world SportyBet JSON fixtures, market models, and edge cases. |

---

## Repository Structure Overview

```text
├── app/
│   ├── analysis/             # Quantitative algorithms (pure mathematical models)
│   │   ├── parlay_builder.py # Target odds, staggered hedging, barbell portfolios, round-robin
│   │   ├── target.py         # Dynamic programming knapsack optimization
│   │   ├── settle.py         # Automatic scoreline & refund leg settlement
│   │   ├── alternatives.py   # Safer & riskier line substitution logic
│   │   └── markets.py        # 4-coordinate scoreline outcome state engine
│   ├── routes/               # Modular Flask blueprints (codes, leagues, games, results, bridge)
│   ├── sources/sportybet/    # Client-side DOM parsing & bookmarklet payload generators
│   ├── templates/            # Clean Jinja2 templates & unified 4-step betting pipeline
│   ├── static/css/style.css  # Modern design system (tokens, floating dock, responsive layout)
│   ├── config.py             # Host authorization, database paths, and upload limits
│   ├── db.py                 # SQLite schema migration and WAL performance configuration
│   └── store.py              # Repository pattern for entities and odds history
├── tests/                    # 168 automated tests covering all modules
├── Dockerfile                # Production multi-stage container build
├── render.yaml               # 1-click Render blueprint specification
├── start.bat / start.sh      # Zero-config local execution scripts
└── README.md                 # Primary project documentation
```
