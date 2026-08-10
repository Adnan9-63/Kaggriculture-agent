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

Days 1-5 focus on getting a provably correct core loop before adding any
complexity: single farmer, wheat only, safety-first (nothing ever goes
unwatered or unfed). Every change gets tested locally before being pushed
— first against a hand-built local approximation of the rules, then
against the real `kaggle-environments` engine to confirm behavior matches.
Bugs, failed assumptions, and design changes get logged below rather than
silently fixed, so the reasoning behind the current version isn't lost.
Hands, animals, additional crops, land expansion, and market-throttling
logic come in afterward, once this base is confirmed stable on the
leaderboard.

## Key decisions log

- **Day 1:** Started with a single farmer, wheat-only, before adding
  hands/animals/other crops — wanted a provably correct core loop first.
  Caught a real bug in testing: harvesting a one-time crop the instant it
  had *any* yield (instead of waiting for it to mature) permanently caps
  yield at 1 unit instead of up to 4, since one-time crops are cleared
  from the tile on harvest. Fixed by adding a per-crop maturity threshold
  before harvesting is allowed.

## Status: Day 1-5

A deliberately simple, safe baseline. Single farmer, wheat-only loop:
water anything unwatered, harvest wheat once it's matured (not the moment
it has *any* yield - see `agent/main.py` comments for why that matters),
plant on empty tiles, sell wheat, buy more seed when out. No hands, no
animals, no land expansion, no premium crops yet.

**Why start this simple:** correctness first. A bot that never lets a
plant die from neglect and never crashes beats a "smart" bot with a bug
in it. Every future phase builds on top of this loop.

## Structure

agent/
main.py - the actual submission (must have an agent(obs) function)
economics.py - offline planning tool, ranks crops/animals by $/tile/day
and glut risk. Not part of the submission.
tests/
mock_harness.py - hand-rolled local simulator (approximate, not the
real rules) for quick sanity checks without
internet access
real_engine_test.py - runs against the REAL kaggle-environments engine.
Run this before trusting any result.


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

Quick sanity check (no internet needed, approximate rules):

```bash
python tests/mock_harness.py
```

Real test (needs `pip install kaggle-environments`, matches actual rules):

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
kaggle competitions submit kaggriculture -f agent/main.py -m "Day 1-5: safe wheat loop"
kaggle competitions submissions kaggriculture     # check status
kaggle competitions episodes <SUBMISSION_ID>       # once it's played games
kaggle competitions leaderboard kaggriculture -s   # check ranking
```

You get 5 submissions/day, only the latest 2 are actively matched - submit
often, no cost to iterating.

## Roadmap

- [x] Day 1-5: safe single-farmer wheat loop
- [ ] Day 6-8: add carrot, hire 2-3 hands with fixed roles (water/harvest/animal duty)
- [ ] Week 2: add animals (goose -> cow), throttled selling for premium goods
- [ ] Week 2-3: land expansion once labor covers it, fertilizer on melon
- [ ] Week 3-4: react to town shop unlocks, tune sell-throttling against real
      market data pulled from replays
- [ ] Week 4-6: iterate against ladder opponents using downloaded replays/logs