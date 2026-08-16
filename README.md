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
- **Day 6, submitted to Kaggle:** first real submission
  (`SubmissionStatus.COMPLETE`, initial rating 600 - the default starting
  rating every submission gets before real match outcomes adjust it).
- **Day 7-10:** added a goose (coop -> buy -> pickup -> place -> daily
  feed/care/harvest), run by one dedicated handler unit on top of the
  existing crop loop. Caught a real bug in testing: with only the farmer
  and no hired hands yet, dedicating the sole unit to the multi-step
  goose project left nothing farming crops at all while it was stuck
  mid-project - the mock harness ran 240 turns doing nothing but PASS.
  Fixed by only activating the goose project once at least one hand is
  hired, so a lone farmer is never pulled off crop duty. Confirmed fixed
  by re-running the harness (matched the exact Day 6 result) and by unit
  tests for every project phase (build coop, buy, pickup, place, feed,
  harvest, care, idle-fallback-to-crops).
- **Day 7-10, real engine regression caught:** first `real_engine_test.py`
  run against the new goose code showed a real drop - 4,833 vs `starter`
  (down from Day 6's 12,258), opponent's score essentially unchanged
  (3,516 vs 3,506). Root cause: with only 2 target hands, dedicating one
  to the goose project cut real crop-tile coverage by a third, and the
  daily feed requirement pulled that hand back to the coop every day for
  the rest of the game - a bad trade for one $50/day animal. Fixed by
  raising the hand target to 3 and only ever assigning the goose project
  to the 3rd hand, once all 3 are hired - the farmer and first 2 hands
  now never get pulled off crop duty. Re-verified with unit tests before
  the next real-engine run (not yet re-run against the real engine as of
  this entry - do that before resubmitting to Kaggle).
- **Day 7-10, submitted to Kaggle:** rating 414.0 shortly after going
  live, above Day 6's 382.8 at the same point. Day 6's own rating kept
  drifting down (600 -> 397 -> 382.8) as it played more real ladder
  opponents - expected, since it's a simpler bot than what many of the
  4,151 competing teams have likely built.
- **Day 11, land expansion:** added `BUY_LAND`, gated on being fully
  staffed (all 3 target hands hired) and having cash to spare - buying
  land before there's labor to work it just locks cash in unused dirt.
  Testing in `tests/full_harness.py` caught a real mistake before it
  shipped: buying all 3 available quadrants ($7,000 total) with only 3
  crop workers (farmer + 2 hands, unchanged since Day 6) left most of
  the new 75 tiles unused - final money came out LOWER than not buying
  land at all (8,230 vs 13,535). Capped land expansion to 1 extra
  quadrant only, matching current labor capacity - re-tested at 14,230,
  a genuine net gain over the no-land baseline. Revisit raising the cap
  once crop-worker count actually scales up in a future day.
- **Day 11, land expansion reverted:** the capped-to-1-quadrant version
  above tested well locally (14,230 vs 13,535) but was a real regression
  against the actual engine: $7,090 vs the Day 7-10 baseline's $9,621,
  reproduced identically across two runs with the same fixed seed. The
  local simulator's flat pricing and lack of weed spawning couldn't
  predict this - most likely cause is that more owned tiles means more
  daily weed-spawn opportunities, and the NE quadrant is genuinely
  farther from the shed hub, costing real travel time the local model
  never charged for. **Land expansion is disabled (`LAND_COST_SEQUENCE =
  []`) until crop-worker count scales up enough to absorb the extra
  distance and weed load.** Lesson: the local simulator is good for
  catching logic bugs (crashes, stuck units, wrong action usage) but
  not reliable for economic tuning decisions - those need the real
  engine, ideally under a fixed seed for a fair before/after comparison.
- **Day 12, scaling crop-worker count:** ran a controlled local sweep of
  `TARGET_HAND_COUNT` (3 through 6) in `tests/full_harness.py` before
  touching the code, applying the Day 11 lesson upfront. Results: money
  peaked at 4 hands (14,255 vs 3 hands' 13,535), flattened at 5, dropped
  at 6 - and wasted-turn count climbed steadily the whole way, confirming
  the 25-tile NW quadrant can't usefully absorb much more than ~4
  workers. Set `TARGET_HAND_COUNT = 4`. **This is a local result only -
  per the Day 11 lesson, treat it as unconfirmed until verified against
  the real engine with the same fixed seed used for the $9,621 baseline.
  Do not submit until that comparison is in hand.**
- **Day 13, cow + throttled milk selling:** generalized the goose's
  handler logic (`animal_handler_action`) to work for any animal/
  structure pair instead of being hardcoded to goose/coop, then added a
  5th hand as a dedicated cow handler (pasture, buy, place, feed/care/
  harvest) on top of the existing goose handler - farmer + first 3 hands
  still never touched, same crop-protection guarantee as Day 7-10's fix.
  Added a per-turn sell cap for milk (`MILK_SELL_CAP_PER_TURN = 3`)
  since it's high glut-risk (above_target 1.60 in economics.py) unlike
  wheat/carrot/egg which stay on bulk-sell. Extended
  `tests/full_harness.py` to simulate PASTURE/COW (it only knew COOP/
  GOOSE before) and verified with unit tests: crop coverage holds with
  only 3 hands, goose handler activates at 4 hands, both handlers run
  independently at 5, milk sell orders cap correctly at 3/turn. Local
  full-season run completed with no errors and both animals successfully
  built/placed/maintained. **Per the Day 11 lesson, the local money
  figure is not treated as meaningful on its own - needs a seeded
  real-engine comparison against the $9,731 Day 12 baseline before
  submitting.**

## Status: Day 13

Farmer + up to 5 hired hands. First 3 stay on crops (wheat, carrot); the
4th runs the goose project, the 5th runs a cow project (pasture, buy,
place, feed/care/harvest) - same crop-protection pattern as goose, never
reassigns an existing crop hand. Milk sells throttled to 3/turn (high
glut risk); wheat/carrot/egg still bulk-sell. Land expansion still
disabled. **Not yet confirmed against the real engine - do not submit
until verified against the $9,731 Day 12 seeded baseline.**

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
only — does not exercise hand/hiring/animal logic):
```bash
python tests/mock_harness.py
```

Real test (needs `pip install kaggle-environments`, matches actual rules,
including hands and the goose project):
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
kaggle competitions submit kaggriculture -f agent/main.py -m "Day 13: cow + throttled milk selling (verify vs 9731 seeded baseline first)"
kaggle competitions submissions kaggriculture     # check status
kaggle competitions episodes <SUBMISSION_ID>       # once it's played games
kaggle competitions leaderboard kaggriculture -s   # check ranking
```

You get 5 submissions/day, only the latest 2 are actively matched - submit
often, no cost to iterating.

## Roadmap

- [x] Day 1-5: safe single-farmer wheat loop
- [x] Day 6: add carrot, hire up to 2 hands with coordinated task assignment
- [x] Day 7-10: goose project (coop, purchase, place, feed/care/harvest)
- [x] Day 11: land expansion attempted, tested and confirmed net-negative
      against the real engine, disabled pending more crop labor
- [ ] Day 12: scale crop hands to 4 - local sweep done, **needs seeded
      real-engine confirmation before submitting** (see decisions log)
- [ ] Day 13: cow + throttled milk selling - built and locally tested,
      **needs seeded real-engine confirmation before submitting**
- [ ] Next: fertilizer on melon, sheep, more premium crops, revisit land
      expansion once labor genuinely scales
- [ ] Week 3-4: react to town shop unlocks, tune sell-throttling against real
      market data pulled from replays
- [ ] Week 4-6: iterate against ladder opponents using downloaded replays/logs
