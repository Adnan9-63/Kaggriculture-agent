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
- **Day 13, real-engine catastrophe caught, two real bugs found and
  fixed:** seeded real-engine test came back at $1,086 - a total
  collapse, WORSE than the opponent's $3,504, down from the $9,731
  baseline. The `hands` column oscillated between 5 and 0 day to day, a
  strong clue something was cyclically failing. Extended
  `tests/full_harness.py` to actually simulate wheat consumption on FEED
  and animal escape after 2 missed days (it modeled neither before), and
  added a turn-by-turn trace script to reproduce it locally. Found TWO
  compounding bugs:
  1. Animals were bought and placed on day 0 - before wheat even
     matures (day 4 for wheat). No amount of "reserve some wheat for
     feeding" can help when total wheat production is still zero; the
     animal starves and escapes within 2 days no matter what.
  2. The wheat reserve itself couldn't build up before any animal
     existed, since the reserve formula was `3 * live_animal_count` -
     zero live animals meant zero reserve, so 100% of wheat kept
     getting sold every turn regardless.
  Both animals were repeatedly starving, escaping, and getting
  re-bought - each cycle a real $300-700 loss, explaining both the
  money collapse and the flickering hand count (money too low to
  afford full hiring some days). Fixed: (a) added
  `WHEAT_BUFFER_BEFORE_ANIMAL_PURCHASE = 5` - won't buy an animal until
  that much wheat is already banked in the shed, and (b) the sell
  logic now reserves that same flat buffer even before any animal
  exists, on top of the existing per-animal feed reserve, so the
  buffer can actually accumulate toward the purchase gate. Also made
  idle handlers hold position at their structure instead of wandering
  into crop work, removing a secondary risk (a long trip back on the
  day feeding is needed again). Re-traced after the fix: exactly 2
  purchases total (1 goose, 1 cow), no further escapes, local money
  improved to $15,165 (previous best was $14,255 without cow). **Still
  needs a fresh seeded real-engine run before submitting - the local
  number is not proof on its own, only the trace confirming the escape
  cycle stopped is.** One more leak caught in the same pass: the flat
  purchase buffer was being reserved even with zero hired hands (no
  chance of ever buying an animal yet), silently costing the
  solo-farmer path real sell revenue for nothing. Fixed by only
  reserving the buffer once hand count actually exceeds the crop-hand
  target; re-confirmed the solo-farmer mock harness result returned to
  the exact $3,300 baseline.
- **Day 13, submitted and confirmed:** real-engine seeded test came back
  at $14,259 vs $3,482 opponent (+46.6% over the $9,731 Day 12
  baseline) - reproduced identically across two runs. Submitted and
  live.
- **Day 14, melon + fertilizer + generalized sell-throttle, two more
  real bugs found and fixed:** added melon (seed cost $80, matures day
  10, capped at 6 yield) with a per-turn sell cap (`SELL_CAP_PER_TURN`
  now covers milk AND melon from one table instead of a milk-only
  special case). Hand-computed the fertilizer economics before writing
  any code: fertilizing wheat/carrot is a net LOSS (fertilizer costs
  $100; wheat's fertilized bonus is only +2 yield units, carrot's only
  +1 - both worth less than $100). Fertilizer only pays off on melon,
  where it doesn't raise the yield cap but reaches it 2 days faster -
  worth far more than $100 across several tiles over a season. Scoped
  fertilizer to melon only (`FERTILIZE_ELIGIBLE_CROPS = {"MELON"}`).

  First real bug: melon seeds were bought but never actually planted -
  `CROP_PRIORITY` always preferred wheat/carrot on any empty tile, and
  since those stay restocked almost continuously, melon never won that
  competition even once purchased. Fixed with `choose_crop_to_plant`,
  giving melon a guaranteed (capped) share of tiles - but gated on
  wheat already having a foothold (`MIN_WHEAT_TILES_BEFORE_MELON = 2`),
  since an early version let melon claim tiles before ANY wheat
  existed, starving cash flow for melon's whole 10-day cycle - caught
  by the short 10-day `mock_harness.py` test going to zero revenue.

  Second, deeper bug, exposed by melon but pre-existing since Day 6:
  `assign_targets` picked whatever target was NEAREST across the
  entire combined list, ignoring priority category entirely. Once
  several wheat tiles matured close together (common with tight early
  cycling), a solo unit kept getting pulled to nearby harvest-ready
  tiles while farther-away tiles went unwatered long enough to turn
  into weeds - a cascade that emptied the whole farm in the 10-day mock
  harness test. This had always been latent; wheat/carrot's fast, even
  cycling rarely triggered it before. Fixed by making `find_targets`
  return separate priority tiers (water / harvest / fertilize / empty)
  and `assign_targets` exhaust each tier before considering the next,
  distance only breaking ties within a tier - never picks a lower-tier
  target while a higher-tier one remains unclaimed.

  Third bug, in the fertilizer-buy logic itself: after queuing a
  `BUY_PRODUCT FERTILIZER` order, the code locally assumed the
  purchase already landed THIS turn, immediately enabling `FERTILIZE`.
  But per spec, player actions process BEFORE market actions each turn
  - so a `FERTILIZE` issued the same turn as the purchase would always
  be evaluated before the purchase resolves, and the real engine would
  reject it. This created a loop "spending" fertilizer that was never
  actually available - caught when a solo-farmer trace showed the
  farmer FERTILIZE-ing the same tile 19 turns straight while everything
  else it owned went unwatered and weeded over. Removed the same-turn
  optimistic assumption; fertilizer only becomes usable starting the
  turn after the purchase actually lands.

  Also discovered `mock_harness.py` had never implemented `DIG` at all
  (a pre-existing gap since Day 1) - once a weed did form, the agent's
  unconditional "DIG if standing on a weed" got stuck in an infinite
  loop against a tile the harness could never actually clear. Added
  proper `DIG`/`BUY_PRODUCT` handling to the harness so this class of
  bug is now actually testable going forward.

  After all fixes: solo-farmer mock harness back to ~baseline (no more
  deadlocks, zero DIG loops), full 30-day multi-unit run holds steady
  at ~$21,300 with matched buy/fertilize counts and zero weeds. **As
  always, the local number is not trusted alone - given how much
  ground got covered this round (3 real bugs), a fresh seeded
  real-engine comparison against the $14,259 Day 13 baseline is
  required before this gets submitted.** Sheep (a natural next animal)
  was deliberately deferred rather than rushed: it shares `PASTURE`
  with cow, and the current `find_structure` only finds the FIRST
  matching structure - two animals sharing one structure kind need a
  way to distinguish which pasture is whose, which needs real design
  thought, not a rushed bolt-on given how many edge cases surfaced in
  this session already.
- **Day 15, sheep - solved the multi-pasture design properly:** gave
  each animal its own "home corner" of the board (goose bottom-right,
  cow top-right, sheep bottom-left; crops already implicitly claim
  top-left via their own forward scan order). Rewrote `find_structure`
  into `find_structure_for_animal`, which disambiguates a PASTURE tile
  three ways: (1) already occupied by the target animal - unambiguous,
  return it; (2) occupied by a DIFFERENT animal from an explicit
  `other_animals` exclusion list - unambiguous, skip it; (3) built but
  still empty - pick whichever candidate is nearest my home corner,
  which reliably tracks the one I built since I always build nearest my
  own corner in the first place. Also generalized the old single-
  `skip_tile` collision guard (Day 13) into a list (`skip_tiles`) so
  three handlers building in the same turn never race for the same
  spot, not just two. Verified with a coordinate-corrected unit test
  (caught my own `tiles[y][x]` mix-up while writing it - x and y really
  do bite back) confirming all three animals get fed independently by
  the right handler, and confirmed via `full_harness.py` that exactly 3
  animals get bought total (not 6+ from an escape loop) and both
  pastures get built once each with no collision. Extended the harness
  for sheep/wool/`SHEEP` cost. Solo-farmer mock harness result
  unchanged from Day 14 baseline (2,975) - no regression.

- **Day 16, land expansion revisited with proportional labor - two more
  real bugs found and fixed, one strong local result:** given a large
  leaderboard gap (our best submission 669.7 vs public top scores in
  the 2,850-3,150 range), land was the obvious biggest untapped lever -
  we use 25 of 100 tiles. Made `TARGET_CROP_HAND_COUNT` dynamic
  (`crop_hand_target(unlocked_quadrants) = CROP_HANDS_PER_QUADRANT *
  quadrant_count`) instead of a fixed 3, so crop-hand count scales with
  land instead of staying flat like the Day 11 attempt that lost money.

  First bug: handler slots were computed as `crop_target + 1/2/3` - a
  growing offset from the FRONT of the hand list. The instant
  crop_target grew (land expanding), whichever hand USED to be "the
  goose handler" got silently reinterpreted as a plain crop hand,
  orphaning its animal mid-game. Confirmed via trace: `BUY_ANIMAL`
  fired 6 times in one run instead of 3, with animals escaping right
  around a land-purchase event. Fixed by indexing handler slots from
  the END of the hand list instead (`len(positions)-3/-2/-1`) - stable
  regardless of how many crop hands sit in front of them, only
  assigned once FULLY staffed for current land.

  Second, this one turned out to be a TEST-HARNESS bug, not an agent
  bug: after the first fix, `BUY_ANIMAL` was STILL firing repeatedly.
  Traced it to `full_harness.py` silently discarding ALL hand inventory
  at day's end instead of depositing it into the shed like the real
  spec requires ("all items in all inventory will be added to shed
  inventory"). An animal picked up but not placed before the day ended
  was just deleted by the simulator, making the agent correctly
  re-detect "no animal anywhere" and re-buy - the agent's own logic was
  fine the whole time. Fixed the harness to properly deposit every
  unit's inventory into the shed (capped at shedCapacity=100) at day
  end. After both fixes: `BUY_ANIMAL` fires exactly 3 times, matching
  goose/cow/sheep, no more phantom re-buys.

  With mechanics confirmed correct, ran a local sweep across
  `CROP_HANDS_PER_QUADRANT` (3-5) and land cap (1-3 extra quadrants):
  only ratio=3 with exactly 1 extra quadrant beat the no-land baseline
  ($26,790 vs $24,465); 2-3 quadrants dropped to $20,910 regardless of
  ratio, and higher ratios flattened out entirely - daily Fibonacci
  re-hiring cost becomes the bottleneck before land does. Locked in
  `LAND_COST_SEQUENCE = [1000]` (1 extra quadrant only) with
  `CROP_HANDS_PER_QUADRANT = 3`. **Given Day 11's precedent - this
  exact local flat-price model already overestimated land's value once
  before by missing weed-spawn scaling and real travel cost - treat
  this local win with real caution. A seeded real-engine comparison
  against the $21,315 Day 15 baseline is required, more so than usual,
  before this gets submitted.**

- **Day 16, land expansion confirmed against the real engine, and
  reverted:** the seeded diagnostic came back at $4,857 vs the $21,315
  no-land baseline - a ~77% collapse, not a marginal loss. The `hands`
  column crashed to 0 repeatedly (days 3-9 especially): the daily
  Fibonacci re-hiring cost for 9 hands (~$88/day) plus the $1,000 land
  purchase plus more seed spending outran real income far worse than
  the flat-price local model predicted, almost certainly because real
  market prices crash under real oversupply in a way no local
  simulator here can see. This is land expansion's SECOND real-engine
  failure despite two different local models (Day 11's and Day 16's)
  both saying it should work. Reverted `LAND_COST_SEQUENCE` back to
  empty. Treating this as a real, settled conclusion for now rather
  than something to keep re-attempting: the current architecture can't
  make land expansion profitable, and a third attempt would need a
  fundamentally different approach (much more gradual scaling, or real
  price-response data pulled from replays) rather than another
  local-sweep-then-hope. Confirmed clean revert: `full_harness.py`
  back to exactly $24,465 with `Quadrants owned: ['NW']` only,
  `BUY_ANIMAL: 3` matching Day 15's clean numbers.

## Status: Day 16

Same as Day 15 (farmer + up to 6 hired hands - 3 crop, goose, cow,
sheep), with the dynamic `crop_hand_target()` infrastructure now in
place but land expansion disabled again after a confirmed severe
real-engine regression (see decisions log). Sheep, melon, fertilizer,
and the generalized sell-throttle table from Days 14-15 remain intact
and are the last real-engine-confirmed economics ($21,315 vs $3,477).
Land expansion is considered a settled dead end for now, not something
to keep retrying without a fundamentally different approach.

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
kaggle competitions submit kaggriculture -f agent/main.py -m "Day 16: land expansion reverted (confirmed regression), Day 15 economics intact"
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
- [x] Day 12: scale crop hands to 4 - real-engine verified 9731 vs 9621, submitted
- [x] Day 13: cow + fixed a real starve/re-buy bug - real-engine verified
      14259 vs 9731, submitted
- [x] Day 14: melon + fertilizer + generalized throttle + 3 real bugs
      fixed - real-engine verified 18071 vs 14259, submitted
- [x] Day 15: sheep, multi-pasture disambiguation solved - real-engine
      verified 21315 vs 18071, submitted (rating jumped to 669.7,
      clear separation from the ~330-390 pack)
- [x] Day 16: land expansion redux with proportional labor scaling -
      confirmed a SECOND real-engine regression despite a promising
      local sweep (4857 vs 21315, -77%). Reverted; land expansion now
      considered a settled dead end pending a fundamentally different
      approach. Day 15 economics resubmitted unchanged.
- [ ] Next: strawberry, tune sell-throttling against real market data
      pulled from replays, study public high-scoring notebooks for
      strategic gaps (leaderboard top scores ~2,850-3,150 vs our 669.7)
- [ ] Week 4-6: iterate against ladder opponents using downloaded replays/logs
