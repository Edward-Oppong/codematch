# CodeMatch design guide

How the site looks and why. Values come from `app/static/css/style.css` and `app/templates/`; change them there and
update this file to match.

## Point of view

CodeMatch is an honest auditor for booking codes. Its one job is to show what a code really is before it's staked: how
likely it is to win and how much of the stake the bookmaker keeps. The design spends its boldness in one place, the
**chance hero** on a code review, and keeps everything else quiet: a calm pitch-green on chalk-white, plain tables with
right-aligned numbers, and boxes only around things you act on.

## Navigation

A bar fixed to the top of every page (`templates/base.html`): the wordmark, five sections, and the theme switch.

| Item | Goes to | Shows |
|---|---|---|
| **Hunt** | `/leagues/singles` | Value Singles Scanner, Custom Parlay Builder, Market Screener, Lowest Margin Markets, League Fixtures |
| **Slip Lab** | `/` | All Saved Codes, Code Hub, Batch Code Surgeon, Fixtures Across Codes |
| **Games** | `/games/` | imported games by date or team, odds steam & line movement tracker |
| **Track** | `/results/` | bets recorded, money in and out, monthly limit, bankroll & Kelly sizing, CLV tracker, personal calibration engine, account longevity shield |
| **Guide** | `/guide` | full walkthrough, button setup, mathematical concepts, glossary, cloud deployment |
| **Sync** | `/import/` | upload files, league-list code, clearing old data |

The current section is a filled ink pill (`aria-current="page"`); sub-pages light up their parent. Sub-pages start with a
back link ("← Codes"). The bar scrolls sideways on narrow phones rather than wrapping.

The core betting workflow is framed by a top **4-Step Pipeline Stepper**:
`1. Pick Leagues → 2. Hunt & Build Slips → 3. Audit & Code Surgeon → 4. Track Bankroll`

```
Codes (Slip Lab)  /
  ├─ Code review            /code/<CODE>
  ├─ Batch Code Surgeon     /codes/batch-surgeon
  └─ Fixtures across codes  /codes/fixtures
Leagues (Hunt)  /leagues/
  ├─ Value Singles Scanner  /leagues/singles
  ├─ Custom Parlay Builder  /leagues/parlay    (Target Odds, Time-Staggered, Zone Portfolio, Round-Robin)
  ├─ Market Screener        /leagues/?mode=screen
  ├─ Lowest Margin Markets  /leagues/margins
  ├─ One pick per game      /leagues/
  └─ Fetch ticked leagues   /leagues/fetch?tid=...
Games  /games/
  ├─ Odds Steam & Line Movement  /games/steam
  └─ One game               /games/<event id>   (?fam=<market family> | other, ?pick=<pick>)
Results (Track)  /results/
  └─ Bankroll, Kelly, CLV, Calibration & Account Shield
Import (Sync)  /import/
```

The footer repeats the honest line (chances are SportyBet's, every bet carries the margin, not affiliated) and holds the
time-zone switch.

## Colour

Tokens on `:root`. Dark mode follows the device unless the theme switch (◐ follow device, ☀ light, ☾ dark) pins it; the
choice is remembered in the browser and applied before the page paints.

| Token | Light | Dark | Used for |
|---|---|---|---|
| `--paper` | `#f2f4f1` | `#121815` | page background (chalk white / night pitch) |
| `--surface` | `#ffffff` | `#1a221e` | tables, forms, hero, snippets |
| `--ink` | `#16211c` | `#e6ebe7` | text, active nav pill |
| `--ink-2` | `#4a5650` | `#a3aea8` | secondary text, table headers |
| `--rule` / `--rule-2` | `#dde2dc` / `#c7cec6` | `#2a3530` / `#3a4741` | lines; input and badge borders |
| `--accent` | `#1f6b4a` | `#6fcf9f` | links, buttons, winning dots, focus ring |
| `--accent-soft` | `#e2efe7` | `#1f3a2d` | step numbers, hover |
| `--sel` | `#f1e08a` | `#4a4220` | the selected pick's row (the only yellow on the page) |

Zones, a muted traffic light. The colours describe how likely a pick is in SportyBet's view, never whether it's good:

| Zone | Odds | Text | Background |
|---|---|---|---|
| Very short | under 1.10 | `--ink-2` | none, outlined |
| Lower risk | 1.10 to 1.49 | `#276c44` / `#7ed3a0` | `#e4f1e8` / `#1c3426` |
| Medium | 1.50 to 1.99 | `#875709` / `#e8b75c` | `#f7ecd6` / `#3a2f1b` |
| Higher risk | 2.00 and up | `#a33a2b` / `#f29a8c` | `#f6e1dd` / `#3d2420` |

Every text and background pair passes WCAG AA (4.5:1) in both themes; the lowest is 5.0:1.

## Type

* **Bricolage Grotesque** (500 to 800) for headings and big figures: characterful, wide numerals.
* **Public Sans** (400 to 700) for everything else, with tabular figures so odds line up in columns.
* Loaded from Google Fonts; without internet the system font is used and nothing breaks.
* Scale: page title 34 px (27 on phones), section 21, sub-section 16, body 15, notes 13.5, footer 13. The chance hero
  scales from 44 to 72 px.
* Line length kept under about 78 characters.

## Layout

* Content up to 1120 px wide, left-aligned, 20 px side padding (14 on phones).
* Numbers right-aligned in tables (`td.num`). Wide tables scroll sideways in their own box; tables marked `.stack` become
  one block per row on phones, each value labelled.
* Corners: 14 px on the hero, 8 px on tables and forms, 4 px on buttons and inputs, full pills for badges and tabs.

## The chance hero

The top of every code review. Left: the chance as **"1 in 315"** (or a percentage at 50% and above) in large type.
Right: a field of dots, one filled dot per expected win, out of 100 plays above 1% or out of 1 ÷ chance plays below it
(up to 1,000 dots). Below: total odds, what comes back on average per 1 staked, what SportyBet keeps, and fair odds, as
a figures strip. The filled dots pop in once when the page opens; that is the page's only automatic motion, and it's
skipped when the device asks for reduced motion.

## Components

| Component | Class | Where |
|---|---|---|
| Flow Stepper | `.flow-tracker` > `.flow-step` | top of core pages: 4-step betting pipeline with clickable stage jumps |
| Floating Booking Dock | `.floating-dock` | docks to screen bottom when ≥1 leg is ticked: live stats & 1-click booking dispatch |
| Strategy Cards | `.strategy-bar` > `.strategy-card` | Custom Parlay Builder: clear interactive cards for algorithmic parlay modes |
| League Box | `.league-filter-box` | clean scrollable container for selecting from 200+ imported leagues |
| Toxicity Badge | `.tox-badge` | Slip Lab & Batch Surgeon: Grades A through F indicating house margin drag |
| Figures strip | `.figures` > `.figure` | numbers in a row split by thin rules (not boxes): hero, results, raise-the-chance |
| Form box | `.card.filters` with `.row` | every filter and entry form |
| Table | `table` inside `.scroll` | everywhere; `.stack` to restack on phones |
| Selected row | `tr.sel` | the pick being looked at |
| Kicked-off row | `tr.past` | greyed text |
| Running totals | `.acc` | league picks: "a code of this pick and all above" |
| Total row | `tr.total` | the short-code builder |
| Collapsible row | `details.fixture` | fixtures across codes, other markets |
| Tabs | `.tabs` | market families on a game page |
| Message | `.msg.ok` / `.msg.bad` | results of an action; bad ones say what went wrong |
| Zone badge | `.zone.z-<key>` | next to every pick |
| Bet chooser | `.bet-group` chips, `details.other-bets` with `.bet-find` | the screener's bet types by category; other markets searchable |
| Main goal row | `.row.goal` | the one tinted form row: "highest-chance selections for total odds of at least…" |
| Odds check | `.odds-check` | under a make-code button once the code is made: odds then → now, picks gone; arrows are neutral, since longer odds aren't better value |
| Fetch box | `details.snippet` | "Fetch with the CodeMatch button", live status while it runs, the console code folded underneath as a fallback |
| CodeMatch button | `.bookmark` | the draggable bookmark on Import |
| Start-here checklist | `ol.start` | empty Codes page; steps tick off as they're done |
| Best right now | `section.best` > `.best-grid` | top of Codes: best open codes by back per 1, best code built from shared fixtures; accent rule on the left |
| Add-codes tabs | `.add-codes` with `.tab` buttons | Code Hub and Paste codes in one box; the last tab used is remembered in the browser |
| Field grid | `.field-grid`, `.pair` | forms with several labelled fields; labels above inputs, wraps by width |
| Explanation fold | `details.explain` | long "how this works" text kept one click away so the tools stay near the top |
| Codes grid on phones | `table.codes` | each saved code as a small grid: figures three across, weakest leg and kick-offs below |
| Sparkline | `svg.spark` | a pick's odds over time, drawn as steps |
| Buttons | `button`, `.secondary`, `.danger`, `.link` | main action, other actions, deleting, small text actions |

Numbered markers are used only where the content really is a sequence: the button set-up steps, the console steps
and the start-here checklist.

On sportybet.com the bookmark shows a small dark box in the bottom-right corner (ink background, paper text) with its
progress ("3 of 20: Premier League") and the result, then removes itself.

## Wording

* Plain words: "chance" not "implied probability", "back per 1 staked" not "expected value", "SportyBet keeps" not
  "overround", "1 in 315" rather than "0.32%" for small chances.
* Every number from SportyBet is labelled as theirs. The app describes; it never tells you a pick is good.
* A chance SportyBet's data doesn't support reads "not given", never a guess. A code's chance is called an estimate.
* Buttons say what happens: "Prepare the fetch", "Fetch with the CodeMatch button", "Record the bet", "Delete ticked".
* Empty pages say what to do next; error messages say what went wrong and how to fix it.
* Odds to two decimals, chances as whole percentages (one decimal in tables), returns to three decimals.
* Times are written in UTC (Ghana time); the footer switch shows them in the device's own time zone instead.
