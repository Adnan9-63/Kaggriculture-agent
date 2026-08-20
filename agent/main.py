"""
Kaggriculture agent - Day 7-10.

New since Day 6: a goose project, run by one dedicated unit (the
DAYE most-recently-hired hand, or the farmer if no hands yet) on top
of the existing crop loop. Chosen because goose is the cheapest animal
(300 vs cow's 400) and has low glut risk on eggs (see agent/economics.py)
- a safe first animal to automate.

Getting an animal running is a multi-step project, unlike a crop:
  1. BUILD_COOP on an empty tile (no cost beyond the tile).
  2. BUY_ANIMAL GOOSE 1 (market order, costs money -> lands in the shed).
  3. A unit must be shed-adjacent and PICKUP the goose into its own
     inventory (buying doesn't hand it to a unit automatically).
  4. That unit walks to the coop and PLACEs the goose on it.
  5. Ongoing: FEED (else it escapes after 2 missed days - same failure
     mode as an unwatered plant), CARE (banks a yield bonus, only pays
     off if the animal is also fed on the next production day), and
     HARVEST eggs whenever yield_units > 0.

Since tiles are fully visible (public state), the handler only needs to
physically visit the coop when it actually needs feeding/caring/
harvesting - we can see that remotely and only send the handler over
when there's real work, freeing it for crop work otherwise.

Still not doing: cow/sheep, land expansion, fertilizer, melon/premium
crops, throttled selling.
"""

BOARD_SIZE = 10
SEED_BUFFER = 200          # cash kept in reserve before buying seed
HAND_CASH_RESERVE = 300    # cash kept in reserve before hiring a hand

# Crop-hand target now SCALES with owned land instead of being fixed at
# 3. Day 12 tested 3 crop hands (farmer+3=4 workers) as the sweet spot
# for exactly ONE 25-tile quadrant - that ratio (1 worker per ~6 tiles)
# is the thing that generalizes, not the flat number 3. As land expands,
# crop_hand_target(unlocked_quadrants) below scales proportionally, so
# a 2nd quadrant gets a 2nd batch of crop hands instead of the same 3
# hands trying to cover 2x the space (which is exactly why the Day 11
# land-expansion attempt lost money - land grew, labor didn't).
CROP_HANDS_PER_QUADRANT = 3
ANIMAL_HANDLER_COUNT = 3   # goose, cow, sheep - constant regardless of land


def crop_hand_target(unlocked_quadrants):
    return CROP_HANDS_PER_QUADRANT * max(1, len(unlocked_quadrants))


def total_hand_target(unlocked_quadrants):
    return crop_hand_target(unlocked_quadrants) + ANIMAL_HANDLER_COUNT

CROP_SEED_COST = {"WHEAT": 10, "CARROT": 20, "MELON": 80}
# "Time to Max Yield" for one-time crops, unfertilized (from the spec
# table). Harvesting before this age locks in a smaller yield than
# waiting, since the tile clears on harvest - no second chance.
CROP_MATURITY_DAY = {"WHEAT": 4, "CARROT": 3, "MELON": 10}
# Order to prefer when planting - cheap staples first (wheat/carrot),
# melon last. Melon is expensive ($80) and slow (10 days to harvest) -
# only worth planting once staples are already stocked, not instead of
# them. NOT profitable to fertilize (see FERTILIZE_ELIGIBLE_CROPS below
# for why wheat/carrot are excluded from that, despite being crops here).
CROP_PRIORITY = ["WHEAT", "CARROT", "MELON"]

# Wheat/carrot get bought to restock almost continuously (see seed-buy
# logic below), which meant melon seeds - always last in CROP_PRIORITY -
# never actually got planted even once bought: any empty tile always had
# wheat or carrot seeds available first. Give melon a guaranteed (but
# capped) share of tiles instead of leaving it to leftover priority -
# modest allocation given melon's long 10-day cycle and the board's
# limited 25 tiles.
MELON_TILE_TARGET = 3
# Don't let melon claim tiles before wheat has a real foothold - a solo
# farmer (or any short early stretch) planting melon FIRST, before any
# wheat exists, starves cash flow for melon's whole 10-day cycle with
# nothing else generating revenue in the meantime. Caught via the short
# 10-day mock_harness test: money went to zero, HARVEST stayed at 0 the
# entire run, because melon got prioritized on turn 1 before any wheat.
MIN_WHEAT_TILES_BEFORE_MELON = 2

# Fertilizer ($100) is only worth it on melon. It doesn't raise melon's
# yield cap (still 6) but reaches that cap at age 8 instead of age 10 -
# 2 extra days of tile throughput per application, worth far more than
# $100 across a season if several melon tiles are running. Wheat/carrot
# are NOT included: fertilizing wheat only adds 2 yield units (~$40-50)
# and carrot only 1 (~$35-40) - both less than the $100 cost, a real net
# loss. Confirmed by hand-computing the economics before writing code,
# not from testing (no local simulator models the harvest-yield formula
# precisely enough to "discover" this - it's read directly off the spec
# table's stated fertilized/unfertilized deltas).
FERTILIZE_ELIGIBLE_CROPS = {"MELON"}
FERTILIZER_COST = 100
FERTILIZER_CASH_RESERVE = 200
# Apply fertilizer while still early in the bonus window (starts age 6)
# so the doubled bonus has time to matter before the window closes at
# age 12. Age 2-7 gives a few turns of slack for a hand to reach the
# tile without missing the window entirely.
FERTILIZE_MIN_AGE = 2
FERTILIZE_MAX_AGE = 7

# Per-turn sell cap for goods where economics.py shows HIGH glut risk
# (above_target >= 1.5) - dumping the whole shed at once would crash
# their own price. Anything not listed here (wheat, carrot, egg) stays
# on bulk-sell; their glut risk is low/medium and bulk-selling is safe.
SELL_CAP_PER_TURN = {
    "MILK": 3,
    "MELON": 2,
    "WOOL": 2,
}

# Fibonacci-ish hire cost sequence, indexed by hires_today (0-indexed).
# Matches farmHandCostMult(=1) * fib(n), fib starting 1,1,2,3,5,8,...
HIRE_COST_SEQUENCE = [1, 1, 2, 3, 5, 8, 13, 21, 34]

ANIMAL_COST = {"GOOSE": 300, "COW": 400, "SHEEP": 500}
ANIMAL_CASH_RESERVE = 300  # keep this much in reserve before buying an animal

# Each animal handler gets its own "home corner" of the NW quadrant so
# structure searches for different animals never spatially collide -
# needed because cow and sheep both use PASTURE, and without separated
# search regions there'd be no reliable way to tell "my pasture" from
# "the other animal's pasture" before an animal is actually placed on
# it (see find_structure_for_animal). Crops implicitly claim top-left
# via their own forward (0,0)-first scan order, so (0,0) is avoided
# here. Corners chosen to spread the three animals across the other
# three corners of the 5x5 NW quadrant (board indices 0-4).
ANIMAL_CORNER = {
    "GOOSE": (4, 4),  # bottom-right
    "COW": (4, 0),    # top-right
    "SHEEP": (0, 4),  # bottom-left
}

TARGET_ANIMAL_HAND_COUNT = 2  # 1 for goose, 1 for cow - added on top of crop hands

# Wheat feeds every animal. Selling it all every turn (as if it were
# only a sell good) can starve animals if selling empties the shed
# before that day's feeding happens - see Day 13 decisions log for the
# real bug this caused (repeated escape/re-buy cycles). Reserve this
# many wheat per live animal before selling the rest.
WHEAT_FEED_RESERVE_PER_ANIMAL = 3

# An animal bought and placed before any wheat has ever been harvested
# starves immediately and escapes within 2 days, no matter how much
# wheat gets reserved later - reserving a share of zero is still zero.
# Testing found exactly this: animals bought on day 0 (before wheat
# matures on day 4) starved and got re-bought every single cycle, a
# repeating $300-700 loss. Require a wheat buffer already banked in the
# shed before buying, so the animal has something to eat from day one.
WHEAT_BUFFER_BEFORE_ANIMAL_PURCHASE = 5

# Costs increase for each quadrant beyond the starting NW one - per spec:
# "$1k, $2k, $4k".
#
# RE-ENABLED (Day 16) with a real fix this time, not just a smaller cap.
# The Day 11 attempt lost money against the real engine even capped at
# just 1 extra quadrant, because crop-hand count never scaled with the
# extra land - more tiles, same labor, so travel time and weed-cleanup
# load ate the gains. This time land purchases are gated on labor
# already being scaled to match CURRENT land (crop_hand_target) before
# the next quadrant is allowed - each purchase must be "earned" by
# labor that's already proven it can keep up, not funded speculatively.
#
# Capped at ONE extra quadrant (not all three), per a local sweep across
# CROP_HANDS_PER_QUADRANT (3-5) and land caps (1-3 quadrants):
#   ratio=3, 1 quadrant  -> $26,790 (best - beats the $24,465 no-land
#                            baseline)
#   ratio=3, 2-3 quadrants -> $20,910 (worse than no land at all)
#   ratio=4/5, any cap   -> flat, ~$22,700-23,900 (staffing cost itself
#                            becomes the bottleneck before land does)
# Diminishing/negative returns kick in fast beyond 1 extra quadrant,
# most likely from the daily re-hiring cost (Fibonacci-scaled) growing
# faster than the marginal land value once headcount gets large. As
# always, this is a LOCAL, flat-price result - Day 11 already showed
# this exact local model overestimates land's value (misses weed-spawn
# scaling and real travel cost), so real-engine verification matters
# even more here than usual before trusting it.
LAND_COST_SEQUENCE = [1000]
LAND_CASH_RESERVE = 500


def is_ready_to_harvest(tile, day):
    crop = tile.get("crop")
    maturity = CROP_MATURITY_DAY.get(crop, 0)
    age = day - tile.get("planted_day", day)
    return tile.get("yield_units", 0) > 0 and age >= maturity


def is_fertilize_eligible(tile, day):
    crop = tile.get("crop")
    if crop not in FERTILIZE_ELIGIBLE_CROPS:
        return False
    if tile.get("fertilized_until_day", -1) != -1:
        return False  # already fertilized this lifecycle
    age = day - tile.get("planted_day", day)
    return FERTILIZE_MIN_AGE <= age <= FERTILIZE_MAX_AGE


def step_toward(pos, target):
    """One axis-aligned move toward target. x first, then y."""
    x, y = pos
    tx, ty = target
    if x < tx:
        return "EAST"
    if x > tx:
        return "WEST"
    if y < ty:
        return "SOUTH"
    if y > ty:
        return "NORTH"
    return None  # already there


def shed_adjacent_positions(board_size):
    half = board_size // 2
    return [(half - 1, half - 1), (half, half - 1), (half - 1, half), (half, half)]


def nearest(pos, candidates):
    if not candidates:
        return None
    return min(candidates, key=lambda c: abs(c[0] - pos[0]) + abs(c[1] - pos[1]))


def find_structure_for_animal(tiles, board_size, kind, target_animal, other_animals, my_corner):
    """Find the structure tile of the given kind that belongs to
    target_animal. Needed because COW and SHEEP both use PASTURE - two
    separate pasture tiles can exist on the board at once, and a naive
    "first one found" search can't tell them apart. Disambiguation:
      1. A structure already holding target_animal is unambiguously
         mine - return it immediately.
      2. A structure holding a DIFFERENT animal from `other_animals`
         (e.g. cow's search skipping a pasture that already has a
         sheep on it) is unambiguously NOT mine - skip it.
      3. Among structures with no animal placed yet (built but empty,
         or genuinely nobody's), pick whichever is nearest my assigned
         "home corner" - since I always build nearest my own corner in
         the first place (see find_nearest_empty_tile), this reliably
         tracks the one I built even before an animal is on it."""
    candidates = []
    for y in range(board_size):
        for x in range(board_size):
            tile = tiles[y][x]
            if isinstance(tile, dict) and tile.get("kind") == kind:
                occupant = tile.get("animal")
                if occupant == target_animal:
                    return (x, y)
                if occupant in other_animals:
                    continue
                candidates.append((x, y))
    if not candidates:
        return None
    return min(candidates, key=lambda p: abs(p[0] - my_corner[0]) + abs(p[1] - my_corner[1]))


def find_nearest_empty_tile(tiles, board_size, corner, skip=None):
    """Find the empty tile nearest to `corner`. Each animal handler gets
    its own corner (goose/cow/sheep each different, crops implicitly
    prefer top-left via their own forward scan order) so builds
    naturally land in separated areas instead of colliding. `skip`
    excludes a tile another handler already claimed THIS turn."""
    best = None
    best_dist = None
    for y in range(board_size):
        for x in range(board_size):
            if tiles[y][x] is None and (x, y) != skip and (skip is None or (x, y) not in skip):
                d = abs(x - corner[0]) + abs(y - corner[1])
                if best_dist is None or d < best_dist:
                    best_dist = d
                    best = (x, y)
    return best


def animal_handler_action(pos, tiles, board_size, money, shed, my_inventory,
                           animal, structure_kind, build_action, my_corner,
                           other_animals=(), skip_tiles=None):
    """Decide a dedicated handler's action for an animal project this
    turn (goose/coop, cow/pasture, or sheep/pasture - same shape either
    way). Returns (action_list, market_order_or_None, is_busy,
    build_target_or_None). build_target is only set while still hunting
    for a spot to build on (before the structure exists) - the caller
    collects these across handlers running the same turn and passes
    them as skip_tiles to the next one, so multiple handlers never race
    to build on the exact same empty tile before any action lands."""
    structure_pos = find_structure_for_animal(
        tiles, board_size, structure_kind, animal, other_animals, my_corner
    )

    if structure_pos is None:
        target = find_nearest_empty_tile(tiles, board_size, my_corner, skip=skip_tiles)
        if target is None:
            return (["PASS"], None, True, None)
        if tuple(pos) == target:
            return ([build_action], None, True, target)
        move = step_toward(pos, target)
        return ([move] if move else ["PASS"], None, True, target)

    structure_tile = tiles[structure_pos[1]][structure_pos[0]]

    if structure_tile.get("animal") is None:
        shed_count = shed.get(animal, 0)
        carried_count = my_inventory.get(animal, 0)

        if carried_count > 0:
            if tuple(pos) == structure_pos:
                return (["PLACE", animal], None, True, None)
            move = step_toward(pos, structure_pos)
            return ([move] if move else ["PASS"], None, True, None)

        if shed_count > 0:
            target = nearest(pos, shed_adjacent_positions(board_size))
            if tuple(pos) == target:
                return (["PICKUP", animal, 1], None, True, None)
            move = step_toward(pos, target)
            return ([move] if move else ["PASS"], None, True, None)

        # Don't buy until wheat is actually being produced - an animal
        # bought before any wheat has been harvested starves and escapes
        # within 2 days no matter what (see Day 13 decisions log).
        order = None
        if (money - ANIMAL_CASH_RESERVE >= ANIMAL_COST[animal]
                and shed.get("WHEAT", 0) >= WHEAT_BUFFER_BEFORE_ANIMAL_PURCHASE):
            order = ["BUY_ANIMAL", animal, 1]
        return (None, order, False, None)

    # animal is placed - only interrupt crop work when it actually needs us
    needs_attention = (
        not structure_tile.get("fed_today")
        or structure_tile.get("yield_units", 0) > 0
        or not structure_tile.get("cared_today")
    )
    if not needs_attention:
        return (None, None, False, None)

    if tuple(pos) != structure_pos:
        move = step_toward(pos, structure_pos)
        return ([move] if move else ["PASS"], None, True, None)

    if not structure_tile.get("fed_today"):
        return (["FEED"], None, True, None)
    if structure_tile.get("yield_units", 0) > 0:
        return (["HARVEST"], None, True, None)
    if not structure_tile.get("cared_today"):
        return (["CARE"], None, True, None)
    return (["PASS"], None, True, None)


def find_targets(tiles, board_size, day, seed_capacity, have_fertilizer):
    """Scan owned (non-LOCKED) tiles for crop work. Returns FOUR SEPARATE
    priority tiers (water, harvest, fertilize, empty-to-plant) instead of
    one flattened list - assign_targets needs them separate to actually
    honor priority order instead of just picking whatever's nearest
    regardless of category (see Day 14 decisions log for the real bug
    this caused: a single farmer got pulled to nearby harvest-ready
    tiles while farther-away tiles went unwatered long enough to turn
    into weeds)."""
    water_targets, harvest_targets, fertilize_targets, empty_targets = [], [], [], []
    for y in range(board_size):
        for x in range(board_size):
            tile = tiles[y][x]
            if tile == "LOCKED":
                continue
            if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                if not tile.get("watered_today"):
                    water_targets.append((x, y))
                elif is_ready_to_harvest(tile, day):
                    harvest_targets.append((x, y))
                elif have_fertilizer and is_fertilize_eligible(tile, day):
                    fertilize_targets.append((x, y))
            elif tile is None:
                empty_targets.append((x, y))
    return [water_targets, harvest_targets, fertilize_targets, empty_targets[:seed_capacity]]


def assign_targets(positions, tiers):
    """Assign each unit (processed in position order) the nearest target
    from the HIGHEST-priority tier that still has any targets left -
    never assigns a lower-tier target while a higher-tier one remains
    unclaimed, even if the lower-tier one is closer. `tiers` is an
    ordered list of target-lists, e.g. [water, harvest, fertilize,
    empty] from find_targets."""
    tiers = [list(t) for t in tiers]
    assignments = []
    for pos in positions:
        assigned = None
        for tier in tiers:
            if not tier:
                continue
            best_i = min(
                range(len(tier)),
                key=lambda i: abs(tier[i][0] - pos[0]) + abs(tier[i][1] - pos[1]),
            )
            assigned = tier.pop(best_i)
            break
        assignments.append(assigned)
    return assignments


def decide_crop_action(pos, tiles, day, remaining_seeds, target, have_fertilizer, remaining_fertilizer, plant_counts):
    x, y = pos
    tile = tiles[y][x]

    if isinstance(tile, dict) and tile.get("kind") == "PLANT":
        if not tile.get("watered_today"):
            return ["WATER"]
        if is_ready_to_harvest(tile, day):
            return ["HARVEST"]
        if have_fertilizer and remaining_fertilizer[0] > 0 and is_fertilize_eligible(tile, day):
            remaining_fertilizer[0] -= 1
            return ["FERTILIZE"]

    if isinstance(tile, dict) and tile.get("kind") == "WEED":
        return ["DIG"]

    if tile is None:
        crop = choose_crop_to_plant(remaining_seeds, plant_counts)
        if crop is not None:
            remaining_seeds[crop] -= 1
            plant_counts[crop] = plant_counts.get(crop, 0) + 1
            return ["PLANT", crop]

    if target is not None and target != (x, y):
        move = step_toward((x, y), target)
        if move:
            return [move]

    return ["PASS"]


def count_plant_tiles_by_crop(tiles, board_size):
    counts = {}
    for y in range(board_size):
        for x in range(board_size):
            tile = tiles[y][x]
            if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                crop = tile.get("crop")
                counts[crop] = counts.get(crop, 0) + 1
    return counts


def choose_crop_to_plant(remaining_seeds, plant_counts):
    """Which crop to plant on an empty tile this turn. Melon gets a
    guaranteed share (up to MELON_TILE_TARGET) instead of always losing
    out to wheat/carrot, which stay restocked almost continuously - see
    Day 14 decisions log for why melon was going unplanted without this.
    But only once wheat has a foothold - melon claiming tiles before any
    cash-generating crop exists starves early cash flow for its whole
    10-day cycle (also Day 14 decisions log)."""
    wheat_established = plant_counts.get("WHEAT", 0) >= MIN_WHEAT_TILES_BEFORE_MELON
    if wheat_established and remaining_seeds.get("MELON", 0) > 0 and plant_counts.get("MELON", 0) < MELON_TILE_TARGET:
        return "MELON"
    for crop in ("WHEAT", "CARROT"):
        if remaining_seeds.get(crop, 0) > 0:
            return crop
    if remaining_seeds.get("MELON", 0) > 0:
        return "MELON"  # staples exhausted too - plant melon anyway
    return None


def count_placed_animals(tiles, board_size):
    """How many animals are actually alive on the farm right now (not
    just how many handlers exist) - used to size the wheat feed reserve."""
    count = 0
    for y in range(board_size):
        for x in range(board_size):
            tile = tiles[y][x]
            if isinstance(tile, dict) and tile.get("kind") in ("COOP", "PASTURE") and tile.get("animal"):
                count += 1
    return count


def hold_position_action(pos, tiles, board_size, structure_kind, animal, other_animals, my_corner):
    """An idle handler's action when its animal doesn't currently need
    attention: stay at (or return to) its structure rather than
    wandering off, so it's instantly available the moment feeding is
    needed again instead of risking a long trip back."""
    structure_pos = find_structure_for_animal(
        tiles, board_size, structure_kind, animal, other_animals, my_corner
    )
    if structure_pos is None or tuple(pos) == structure_pos:
        return ["PASS"]
    move = step_toward(pos, structure_pos)
    return [move] if move else ["PASS"]


def agent(obs):
    player = obs["player"]
    day = obs["day"]
    hour = obs["hour"]
    me = obs["farms"][player]
    private = obs["private"]
    tiles = me["tiles"]
    board_size = len(tiles)

    money = me["money"]
    seeds = dict(private["seeds"])
    shed = private["shed"]
    inventories = private.get("inventories", [])
    unlocked_quadrants = me.get("unlocked_quadrants", ["NW"])
    crop_target = crop_hand_target(unlocked_quadrants)

    market = []

    # --- sell: wheat/carrot/egg have low/medium glut risk, bulk-sell is
    #     safe (see economics.py). Milk is HIGH glut risk (above_target
    #     1.60) - dumping the whole shed at once would crash its own
    #     price, so cap how much sells per turn instead.
    #
    #     WHEAT is also what feeds every animal. Selling 100% of it every
    #     turn was a real bug (see Day 13 decisions log): with two
    #     animals now competing for the same wheat, our own sell order
    #     could empty the shed before that day's feeding happened, an
    #     animal would starve, escape after 2 missed days, and get
    #     re-bought - a $300-400 loss repeating over and over. Reserve
    #     enough wheat per live animal before selling the rest. ---
    # Reserve enough to cover live animals' daily feed, PLUS the flat
    # purchase buffer so it can actually accumulate BEFORE any animal
    # exists - otherwise selling 100% of wheat pre-purchase means the
    # buy-gate threshold above never gets reached at all. Only reserve
    # the purchase buffer once there's actually hand capacity for a
    # handler - no point withholding wheat for an animal that has no
    # chance of being bought yet (e.g. solo farmer, early game).
    animal_count = count_placed_animals(tiles, board_size)
    have_handler_capacity = len(me.get("hands", [])) > crop_target
    wheat_reserve = WHEAT_FEED_RESERVE_PER_ANIMAL * animal_count
    if have_handler_capacity:
        wheat_reserve += WHEAT_BUFFER_BEFORE_ANIMAL_PURCHASE
    for item in ("WHEAT", "CARROT", "EGG"):
        n = shed.get(item, 0)
        if item == "WHEAT":
            n = max(0, n - wheat_reserve)
        if n > 0:
            market.append(["SELL", item, n])
    # Generalized throttled sell for every high-glut-risk good (was
    # milk-only; melon needed the same treatment - above_target 3.60,
    # even worse than milk's 1.60 - so this now covers both from one
    # table instead of duplicating the same pattern per-item).
    for item, cap in SELL_CAP_PER_TURN.items():
        n = shed.get(item, 0)
        if n > 0:
            market.append(["SELL", item, min(n, cap)])

    # --- buy seed for whichever crop we're out of, cheapest first ---
    for crop in CROP_PRIORITY:
        cost = CROP_SEED_COST[crop]
        if seeds.get(crop, 0) == 0 and money - SEED_BUFFER >= cost:
            affordable = int((money - SEED_BUFFER) // cost)
            buy_n = max(1, min(affordable, 10))
            market.append(["BUY_SEED", crop, buy_n])
            money -= buy_n * cost
            seeds[crop] = seeds.get(crop, 0) + buy_n
            break

    # --- buy fertilizer only if there's an eligible tile waiting for it -
    #     no point holding inventory with nothing to apply it to.
    #
    #     IMPORTANT: do NOT locally assume this turn's purchase already
    #     landed (no "fertilizer_n = 1" here). Per spec, player actions
    #     process BEFORE market actions each turn - so a FERTILIZE issued
    #     this same turn would always be evaluated before this BUY_PRODUCT
    #     order even resolves, and the real engine would reject it every
    #     time. This was a real bug: it created a loop of "spending"
    #     fertilizer that was never actually available yet, discovered
    #     via a solo-farmer test that got stuck FERTILIZE-ing the same
    #     tile for 19 consecutive turns while everything else it owned
    #     went unwatered and turned to weeds. Fertilizer only becomes
    #     usable starting the turn AFTER the purchase actually lands. ---
    fertilizer_n = shed.get("FERTILIZER", 0)
    if fertilizer_n == 0 and money - FERTILIZER_CASH_RESERVE >= FERTILIZER_COST:
        has_eligible_tile = any(
            isinstance(tiles[y][x], dict) and is_fertilize_eligible(tiles[y][x], day)
            for y in range(board_size) for x in range(board_size)
            if tiles[y][x] != "LOCKED"
        )
        if has_eligible_tile:
            market.append(["BUY_PRODUCT", "FERTILIZER", 1])
            money -= FERTILIZER_COST

    # --- hire hands at the start of the day if we can afford it. Target
    #     scales with owned land (crop_target = crop_hand_target(...))
    #     instead of a fixed number, so a farm with 2 quadrants hires
    #     enough crop hands for 2 quadrants' worth of work, not the same
    #     count that only ever matched a single quadrant. ---
    hires_today = me.get("hires_today", 0)
    current_hands = len(me.get("hands", []))
    hand_target = crop_target + ANIMAL_HANDLER_COUNT
    if hour == 0:
        while current_hands < hand_target and hires_today < len(HIRE_COST_SEQUENCE):
            cost = HIRE_COST_SEQUENCE[hires_today]
            if money - HAND_CASH_RESERVE < cost:
                break
            market.append(["HIRE"])
            money -= cost
            hires_today += 1
            current_hands += 1

    # --- buy the NEXT quadrant only once labor is already fully scaled
    #     to match CURRENT land - each purchase must be "earned" by
    #     labor that's already proven it can keep up with what we have,
    #     not funded speculatively ahead of it. Day 11 lost money buying
    #     land without this gate; see decisions log. ---
    if hour == 0 and current_hands >= hand_target:
        land_idx = len(unlocked_quadrants) - 1
        if 0 <= land_idx < len(LAND_COST_SEQUENCE):
            land_cost = LAND_COST_SEQUENCE[land_idx]
            if money - LAND_CASH_RESERVE >= land_cost:
                market.append(["BUY_LAND"])
                money -= land_cost

    # --- positions: farmer first, then hands. Handlers are the LAST 3
    #     hands - goose, then cow, then sheep - and only once ALL target
    #     hands are hired. The farmer and first crop_target hands must
    #     never be pulled off crop duty. Testing (Day 7-10) showed a
    #     large regression when an existing crop hand got reassigned
    #     instead: cut real crop-tile coverage by a third, and the
    #     animal's daily feed requirement pulled that hand back every
    #     day for the rest of the game - a bad trade for one animal's
    #     income. ---
    positions = [me["farmer"]] + list(me["hands"])
    # Handler slots are the LAST 3 hands (by position, not a growing
    # offset from the front) - stable even as crop_target grows when
    # land expands. An offset-from-front scheme (crop_target+1/2/3)
    # reinterprets whichever hand USED to be "the goose handler" as a
    # plain crop hand the instant crop_target grows, orphaning its
    # animal mid-game and triggering the exact starve/re-buy pattern
    # from Day 13 - confirmed by testing: BUY_ANIMAL fired 6 times in
    # one 30-day run instead of 3, with an unplaced sheep stuck in the
    # shed at the end. Only assign these roles once FULLY staffed for
    # current land (crop_target crop hands + all 3 animal handlers) -
    # otherwise a hand still needed for crop duty could get misread as
    # a spare animal handler mid-transition.
    fully_staffed = len(positions) >= crop_target + ANIMAL_HANDLER_COUNT + 1
    if fully_staffed:
        goose_slot = len(positions) - 3
        cow_slot = len(positions) - 2
        sheep_slot = len(positions) - 1
    else:
        goose_slot = cow_slot = sheep_slot = None

    handler_slots = {}  # slot index -> action_list, for ALL handler slots
                         # (busy or idle) - handlers NEVER do crop work,
                         # even when idle. Testing found that letting an
                         # idle handler wander into crop tasks could put
                         # it far from its structure by the time the
                         # animal needed feeding again, missing the
                         # window and causing a starve/escape/re-buy
                         # cycle - see Day 13 decisions log. An idle
                         # handler instead holds position at its
                         # structure, trading a little unused labor for
                         # guaranteed same-turn feed response.
    build_targets_this_turn = []  # tiles already claimed by an earlier
                                   # handler this turn, so a later one
                                   # never races to build on the same spot

    ANIMAL_HANDLERS = [
        (goose_slot, "GOOSE", "COOP", "BUILD_COOP", ()),
        (cow_slot, "COW", "PASTURE", "BUILD_PASTURE", ("SHEEP",)),
        (sheep_slot, "SHEEP", "PASTURE", "BUILD_PASTURE", ("COW",)),
    ]

    for slot, animal, structure_kind, build_action, other_animals in ANIMAL_HANDLERS:
        if slot is None or len(positions) <= slot:
            continue
        pos = positions[slot]
        inv = inventories[slot] if slot < len(inventories) else {}
        action, order, busy, build_target = animal_handler_action(
            pos, tiles, board_size, money, shed, inv,
            animal=animal, structure_kind=structure_kind, build_action=build_action,
            my_corner=ANIMAL_CORNER[animal], other_animals=other_animals,
            skip_tiles=build_targets_this_turn,
        )
        if order:
            market.append(order)
        if build_target:
            build_targets_this_turn.append(build_target)
        if busy:
            handler_slots[slot] = action
        else:
            handler_slots[slot] = hold_position_action(
                pos, tiles, board_size, structure_kind,
                animal, other_animals, ANIMAL_CORNER[animal],
            )

    # --- coordinate remaining (non-handler-busy) units on crop tasks ---
    crop_unit_indices = [i for i in range(len(positions)) if i not in handler_slots]
    crop_positions = [positions[i] for i in crop_unit_indices]

    seed_capacity = sum(seeds.values())
    have_fertilizer = fertilizer_n > 0
    targets = find_targets(tiles, board_size, day, seed_capacity, have_fertilizer)
    assignments = assign_targets(crop_positions, targets)

    remaining_seeds = dict(seeds)
    remaining_fertilizer = [fertilizer_n]  # mutable single-element list, shared
                                            # across units so a second unit
                                            # can't apply fertilizer we no
                                            # longer have this turn
    plant_counts = count_plant_tiles_by_crop(tiles, board_size)
    actions = [None] * len(positions)
    for list_i, unit_i in enumerate(crop_unit_indices):
        actions[unit_i] = decide_crop_action(
            positions[unit_i], tiles, day, remaining_seeds, assignments[list_i],
            have_fertilizer, remaining_fertilizer, plant_counts,
        )

    for slot, action in handler_slots.items():
        actions[slot] = action

    return {
        "farmer": actions[0],
        "hands": actions[1:],
        "market": market,
    }
