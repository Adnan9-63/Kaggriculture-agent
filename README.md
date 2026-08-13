# Kaggriculture Agent

## About

This repo is my agent for **Kaggriculture**, a Kaggle featured simulation
competition. Two agents compete head-to-head on separate 10x10 farms over
a 30-day season (720 turns), managing crops, animals, land, hired labor,
and a dynamic market economy. Whoever has the most money at the end wins.

- **Competition page:** https://kaggle.com/competitions/kaggriculture
- **Prize pool:** $50,000 total, $5,000 to each of the top 10 places
- **Entry deadline:** Sept 23, 2026
- **Final submission deadline:** Sept 30, 2026
- **Leaderboard finalizes:** ~Oct 15, 2026 (games keep running ~2 weeks after
  final submission to reduce rating uncertainty)
- **Ranking:** Elo-style skill rating from wins/losses/ties, finalized via a
  Bradley-Terry tournament on the accumulated episodes

## Strategy philosophy

The game *looks* like "grow the most valuable stuff," but the market
mechanics punish that directly: every resource has a price curve that
falls as you sell more of it, and premium goods (melon, strawberry, milk,
wool) fall much harder than staples (wheat, carrot, eggs) when oversold.
See `agent/economics.py` for the actual numbers.

So the real competition is:
1. **Never lose value to neglect** — an unwatered plant becomes a
   worthless weed in 2 days, an unfed animal escapes permanently. This is
   the single most common way a "clever" bot underperforms a boring one.
2. **Diversify and throttle** — staples for reliable bulk income, premium
   goods sold in small batches so you don't crash your own market.
3. **Scale labor before land** — buying new quadrants is only worth it if
   you can actually keep the new tiles watered/harvested; hired hands are
   cheap early (Fibonacci pricing resets daily) and are the real lever.
4. **Time production against town demand** — new shops unlock periodically
   and permanently increase demand for specific goods; production that
   anticipates this beats production that ignores it.

## Development approach

Days 1-5 focused on getting a provably correct core loop before adding any
complexity: single farmer, wheat only, safety-first (nothing ever goes
unwatered or unfed). Every change gets tested locally before being pushed
— first against a hand-built local approximation of the rules, then
against the real `kaggle-environments` engine to confirm behavior matches.
Bugs, failed assumptions, and design changes get logged below rather than
silently fixed, so the reasoning behind the current version isn't lost.
Day 6 onward starts layering in labor scaling (hands), crop diversity,
animals, land expansion, and market-throttling logic, always validated
against the real engine before being trusted.

## Key decisions log

- **Day 1:** Started with a single farmer, wheat-only, before adding
  hands/animals/other crops — wanted a provably correct core loop first.
  Caught a real bug in testing: harvesting a one-time crop the instant it
  had *any* yield (instead of waiting for it to mature) permanently caps
  yield at 1 unit instead of up to 4, since one-time crops are cleared
  from the tile on harvest. Fixed by adding a per-crop maturity threshold
  before harvesting is allowed.
- **Day 1-5, real engine confirmation:** ran `tests/real_engine_test.py`
  against the actual `kaggle-environments` package. Result: 10,152 vs 0
  against the built-in `random` agent, and 7,624 vs 3,506 against the
  built-in `starter` agent — both `status=DONE`, no errors. Confirms the
  agent's interface and core loop are correct against the real rules, not
  just the local approximation.
- **Day 6:** Added farm hands and a second crop (carrot). The main design
  problem this introduces: multiple units acting in the same turn can
  collide — two units both trying to plant the last seed in one turn
  causes the game to silently discard *both* plant actions. Solved by
  building one shared task list (water > harvest > plant) per turn,
  assigning each unit its nearest unclaimed task, and tracking a local
  seed budget as each unit's action is decided so later units see an
  accurate remaining count. `tests/mock_harness.py` doesn't simulate
  hands (single-farmer only), so hiring/coordination logic is only
  validated by `tests/real_engine_test.py` against the real engine.

## Status: Day 6

Farmer + up to 2 hired hands now work the farm together, coordinated so
they never collide on the same tile or seed in a turn. Two crops in
rotation (wheat, carrot). Hands are hired automatically at the start of
each day once cash allows. Still no animals, land expansion, fertilizer,
or premium crops — those come once this labor-scaling loop is confirmed
stable on the real engine.

## Structure

```
agent/
  main.py        - the actual submission (must have an `agent(obs)` function)
  economics.py   - offline planning tool, ranks crops/animals by $/tile/day
                   and glut risk. Not part of the submission.
tests/
  mock_harness.py     - hand-rolled local simulator (approximate, single
                         farmer only, no hand simulation) for quick sanity
                         checks without internet access
  real_engine_test.py - runs against the REAL kaggle-environments engine.
                         Run this before trusting any result, especially
                         for hand/hiring behavior.
```

## Setup (run this on your machine)

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Kaggle CLI auth (only needed for submitting, not for local testing):
```bash
mkdir -p ~/.kaggle
# paste your API token (from kaggle.com/settings/api) into ~/.kaggle/access_token
chmod 600 ~/.kaggle/access_token
```

## Test locally

Quick sanity check (no internet needed, approximate rules, single farmer
only — does not exercise hand/hiring logic):
```bash
python tests/mock_harness.py
```

Real test (needs `pip install kaggle-environments`, matches actual rules,
including hands):
```bash
python tests/real_engine_test.py
```

Look at reward/status for each player. `status` should be `DONE`, not
`ERROR` - if it's `ERROR`, the agent crashed and you need the traceback
(kaggle-environments prints agent stderr when `debug=True`).

## Economic model

```bash
python agent/economics.py
```

Prints a ranked table of $/tile/day and "glut risk" (how hard a resource's
price crashes if you dump too much in one day) for every crop/animal. Use
this to decide what to add next, not gut feel.

## Submit to Kaggle

```bash
kaggle competitions submit kaggriculture -f agent/main.py -m "Day 6: hands + carrot"
kaggle competitions submissions kaggriculture     # check status
kaggle competitions episodes <SUBMISSION_ID>       # once it's played games
kaggle competitions leaderboard kaggriculture -s   # check ranking
```

You get 5 submissions/day, only the latest 2 are actively matched - submit
often, no cost to iterating.

## Roadmap

- [x] Day 1-5: safe single-farmer wheat loop
- [x] Day 6: add carrot, hire up to 2 hands with coordinated task assignment
- [ ] Day 7-10: animals (goose -> cow), throttled selling for premium goods
- [ ] Week 2-3: land expansion once labor covers it, fertilizer on melon
- [ ] Week 3-4: react to town shop unlocks, tune sell-throttling against real
      market data pulled from replays
- [ ] Week 4-6: iterate against ladder opponents using downloaded replays/logs
