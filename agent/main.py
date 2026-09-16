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
ANIMAL_HANDLER_COUNT = 3

def crop_hand_target(unlocked_quadrants):
    return min(10, CROP_HANDS_PER_QUADRANT * max(1, len(unlocked_quadrants)))

def total_hand_target(unlocked_quadrants):
    return min(13, crop_hand_target(unlocked_quadrants) + ANIMAL_HANDLER_COUNT)

def dynamic_cash_reserve(unlocked_quadrants):
    hand_target = total_hand_target(unlocked_quadrants)
    return sum(HIRE_COST_SEQUENCE[:hand_target]) + 100

CROP_SEED_COST = {"WHEAT": 10, "CARROT": 20, "MELON": 80, "STRAWBERRY": 100}
CROP_MATURITY_DAY = {"WHEAT": 4, "CARROT": 3, "MELON": 10, "STRAWBERRY": 10}
CROP_PRIORITY = ["WHEAT", "STRAWBERRY", "MELON"]  # STRAWBERRY temporarily
# removed for isolation testing (see STRAWBERRY_TILE_TARGET above) -
# excluded here too so seed-buying never touches it either, for a
# clean test. Restore "STRAWBERRY" to this list once isolated.

# Strawberry is ONGOING (like tomato), not one-time like wheat/carrot/
# melon: it produces repeatedly at fixed ages (10, 12, 14, 16 - spec:
# "strawberry at ages 10, 12, 14, 16") instead of a single harvest that
# clears the tile. HARVEST must NOT be treated as "remove the plant"
# for these - is_ready_to_harvest and the harvest action itself are
# already generic (just "yield_units > 0 and age >= first-yield-age"),
# so no agent-decision-logic change is needed; this only matters for
# accurately SIMULATING it in the local test harnesses, which
# previously assumed every harvest clears the tile (fine for one-time
# crops, wrong for ongoing ones - see tests/full_harness.py).
ONE_TIME_CROPS = {"WHEAT", "CARROT", "MELON"}
ONGOING_CROP_SCHEDULE = {"STRAWBERRY": (10, 12, 14, 16)}

def get_strawberry_target(unlocked_quadrants, prices):
    
    target = 10
    if prices.get("STRAWBERRY", 120) < 50:
        target = 2
    elif prices.get("STRAWBERRY", 120) > 150:
        target = 15
    return target * max(1, len(unlocked_quadrants))


def get_melon_target(unlocked_quadrants, prices):
    
    target = 5
    if prices.get("MELON", 250) < 100:
        target = 1
    elif prices.get("MELON", 250) > 300:
        target = 8
    return target * max(1, len(unlocked_quadrants))


MIN_WHEAT_TILES_BEFORE_MELON = 2

FERTILIZE_ELIGIBLE_CROPS = {"MELON", "STRAWBERRY"}
SURPLUS_ELIGIBLE_CROPS = set()
FERTILIZER_SURPLUS_THRESHOLD = 10
FERTILIZER_COST = 100
FERTILIZER_CASH_RESERVE = 200

FERTILIZE_WINDOW = {
    "MELON": (2, 7),
    "STRAWBERRY": (8, 14),
    "WHEAT": (2, 4)
}

# Per-turn sell cap for goods where economics.py shows HIGH glut risk
# (above_target >= 1.5) - dumping the whole shed at once would crash
# their own price. Anything not listed here (wheat, carrot, egg) stays
# on bulk-sell; their glut risk is low/medium and bulk-selling is safe.
# These are the FLOOR/base caps - actual per-turn cap is adjusted up or
# down from here based on the CURRENT market price relative to base
# price (see dynamic_sell_quantity below), instead of a single flat
# number regardless of how healthy or crashed the price already is.
SELL_CAP_PER_TURN = {
    "MILK": 3,
    "MELON": 2,
    "WOOL": 2,
    "STRAWBERRY": 2,
}

# Base market price for every sellable good (from the spec's price
# table / economics.py) - used only to compute price_ratio =
# current_price / base_price, a cheap read of "is this price healthy,
# or already crashed" without needing the full price-curve formula.
BASE_PRICE = {
    "WHEAT": 25, "CARROT": 35, "TOMATO": 60, "STRAWBERRY": 120,
    "MELON": 250, "EGG": 50, "MILK": 160, "WOOL": 200, "FERTILIZER": 100,
}

# Thresholds for price_ratio = current_price / base_price.
PRICE_RATIO_HEALTHY = 0.75   # at/above this, price has room - sell more
PRICE_RATIO_CRASHED = 0.40   # at/below this, price is already hurting -
                              # sell less, let it recover instead of
                              # grinding it further toward the floor


def dynamic_sell_quantity(available, current_price, item, day, base_cap=None):
    """How much of `item` to sell this turn, reacting to the ACTUAL
    current market price instead of a fixed guess. `base_cap` is the
    normal per-turn ceiling for throttled goods (None means normally
    unlimited, i.e. bulk-sell staples). Below PRICE_RATIO_CRASHED, sell
    much less regardless of category - even a "safe" staple grinds its
    own price further down if dumped while already depressed.

    Deliberately does NOT sell MORE than base_cap even when price is
    healthy - tried that first (double the cap above
    PRICE_RATIO_HEALTHY) and it was a confirmed real-engine regression
    (-8.2%, $19,564 vs $21,315 baseline). Root cause: for the steepest
    glut-risk goods (melon above_target 3.60, wool 3.20), selling MORE
    right when price recovers is exactly what pushes it straight back
    into crash territory - the original flat, conservative cap was
    already doing its job correctly for those, and the "sell more when
    healthy" idea undid that safety margin. Only ever throttling DOWN
    (never up) keeps the easing-off behavior, which is unambiguously
    safe, without the harmful half."""
    if available <= 0:
        return 0
    base_price = BASE_PRICE.get(item)
    if not base_price:
        return available if base_cap is None else min(available, base_cap)
    price_ratio = current_price / base_price

    if base_cap is None:
        if price_ratio <= 0.30:
            return 0  # Hold for recovery
        if price_ratio <= 0.50:
            return min(available, max(1, available // 4))
        return available

    if price_ratio <= 0.30:
        cap = 0  # Hold for recovery
    elif price_ratio <= 0.50:
        cap = max(0, base_cap // 2)
    else:
        cap = base_cap
    
    # Panic dump at the end of the game
    if day >= 29:
        cap = max(cap, 10) # 10 is the market order limit anyway
        if cap == 0:
            cap = 10
        
    return min(available, cap)

# Fibonacci-ish hire cost sequence, indexed by hires_today (0-indexed).
# Matches farmHandCostMult(=1) * fib(n), fib starting 1,1,2,3,5,8,...
HIRE_COST_SEQUENCE = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377, 610, 987, 1597]

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
# DISABLED again (Day 16). Re-enabled with proportional labor scaling
# and looked promising locally ($26,790 vs $24,465 no-land, even 1
# quadrant only) - but against the REAL engine it was a severe
# regression: $4,857 vs the $21,315 no-land baseline, a ~77% drop. The
# `hands` count crashed to 0 repeatedly in the seeded diagnostic (days
# 3-9 especially) - the daily Fibonacci re-hiring cost for 9 hands
# (~$88/day) plus the $1,000 land purchase plus more seed spending
# outran real income far worse than the flat-price local model
# predicted, almost certainly because real market prices crash under
# real oversupply in a way no local simulator here can see. This is
# land expansion's SECOND real-engine failure despite two different
# local models both saying it should work - strong enough evidence to
# stop patching around it rather than trying a third variant. Any
# future attempt needs a fundamentally different approach (much more
# gradual scaling, or real price-response data from replays), not
# another local-sweep-then-hope.
LAND_COST_SEQUENCE = [1000, 2000, 4000]


def is_ready_to_harvest(tile, day):
    crop = tile.get("crop")
    maturity = CROP_MATURITY_DAY.get(crop, 0)
    age = day - tile.get("planted_day", day)
    return tile.get("yield_units", 0) > 0 and age >= maturity


def is_fertilize_eligible(tile, day, fertilizer_n=0, for_purchase=False):
    crop = tile.get("crop")
    if for_purchase:
        if crop not in FERTILIZE_ELIGIBLE_CROPS:
            return False
    else:
        if crop not in FERTILIZE_ELIGIBLE_CROPS:
            if crop not in SURPLUS_ELIGIBLE_CROPS or fertilizer_n <= FERTILIZER_SURPLUS_THRESHOLD:
                return False

    if tile.get("fertilized_until_day", -1) != -1:
        return False  # already fertilized this lifecycle
    age = day - tile.get("planted_day", day)
    if crop == 'STRAWBERRY':
        return age in (10, 12, 14)
    w_min, w_max = FERTILIZE_WINDOW.get(crop, (99, 99))
    return w_min <= age <= w_max


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
                           other_animals=(), skip_tiles=None, unlocked_quadrants=None):
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
        if (money - dynamic_cash_reserve(unlocked_quadrants) >= ANIMAL_COST[animal]
                and shed.get("WHEAT", 0) >= WHEAT_BUFFER_BEFORE_ANIMAL_PURCHASE):
            order = ["BUY_ANIMAL", animal, 1]
        return (None, order, False, None)

    # animal is placed - only interrupt crop work when it actually needs
    # us. Includes fertilizer_available: every surviving animal makes 1
    # fertilizer available daily for free (spec), and we were leaving it
    # uncollected entirely - a real waste, since we're separately
    # spending real money (BUY_PRODUCT) on the exact same resource for
    # melon fertilizing. Uncollected fertilizer doesn't decay or expire
    # (spec: "an animal left alone for five days still yields 1 unit"),
    # so it's safe to treat as lowest priority - collect whenever there's
    # nothing more urgent, never at the expense of feed/harvest/care.
    needs_attention = (
        not structure_tile.get("fed_today")
        or structure_tile.get("yield_units", 0) > 0
        or not structure_tile.get("cared_today")
        or structure_tile.get("fertilizer_available", False)
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
    if structure_tile.get("fertilizer_available", False):
        return (["COLLECT_FERTILIZER"], None, True, None)
    return (["PASS"], None, True, None)


def find_targets(tiles, board_size, day, seed_capacity, fertilizer_n):
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
                elif fertilizer_n > 0 and is_fertilize_eligible(tile, day, fertilizer_n=fertilizer_n):
                    fertilize_targets.append((x, y))
                elif is_ready_to_harvest(tile, day):
                    harvest_targets.append((x, y))
            elif tile is None:
                empty_targets.append((x, y))
    return [water_targets, fertilize_targets[:fertilizer_n], harvest_targets, empty_targets[:seed_capacity]]


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


def decide_crop_action(pos, tiles, day, remaining_seeds, target, remaining_fertilizer, plant_counts, 
unlocked_quadrants, market_prices):
    x, y = pos
    tile = tiles[y][x]

    if isinstance(tile, dict) and tile.get("kind") == "PLANT":
        if not tile.get("watered_today"):
            return ["WATER"]
        if remaining_fertilizer[0] > 0 and is_fertilize_eligible(tile, day, fertilizer_n=remaining_fertilizer[0]):
            remaining_fertilizer[0] -= 1
            return ["FERTILIZE"]
        if is_ready_to_harvest(tile, day):
            return ["HARVEST"]

    if isinstance(tile, dict) and tile.get("kind") == "WEED":
        return ["DIG"]

    if tile is None:
        crop = choose_crop_to_plant(remaining_seeds, plant_counts, unlocked_quadrants, day, market_prices)
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


def choose_crop_to_plant(remaining_seeds, plant_counts, unlocked_quadrants, day, prices):
    target_strawberry = get_strawberry_target(unlocked_quadrants, prices)
    target_melon = get_melon_target(unlocked_quadrants, prices)
    wheat_established = plant_counts.get("WHEAT", 0) >= MIN_WHEAT_TILES_BEFORE_MELON
    
    # Do not plant crops if they won't mature before the end of the 30-day season (day 29 is the last day)
    # Strawberry: 10 days. Melon: 8 days. Carrot: 3 days. Wheat: 4 days.
    can_plant_strawberry = day <= 19
    can_plant_melon = day <= 21
    can_plant_wheat = day <= 25
    can_plant_carrot = day <= 26

    if wheat_established:
        if can_plant_strawberry and remaining_seeds.get("STRAWBERRY", 0) > 0 and plant_counts.get("STRAWBERRY", 0) < target_strawberry:
            return "STRAWBERRY"
        if can_plant_melon and remaining_seeds.get("MELON", 0) > 0 and plant_counts.get("MELON", 0) < target_melon:
            return "MELON"
    for crop in ("WHEAT", "CARROT"):
        if (crop == "WHEAT" and not can_plant_wheat) or (crop == "CARROT" and not can_plant_carrot):
            continue
        if remaining_seeds.get(crop, 0) > 0:
            return crop
    for crop in ("STRAWBERRY", "MELON"):
        if (crop == "STRAWBERRY" and not can_plant_strawberry) or (crop == "MELON" and not can_plant_melon):
            continue
        if remaining_seeds.get(crop, 0) > 0:
            return crop
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
    plant_counts = count_plant_tiles_by_crop(tiles, board_size)

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
    market_prices = obs.get("market", {}).get("prices", {})

    for item in ("WHEAT", "CARROT", "EGG", "FERTILIZER"):
        n = shed.get(item, 0)
        if item == "WHEAT":
            n = max(0, n - wheat_reserve)
        elif item == "FERTILIZER":
            n = max(0, n - FERTILIZER_SURPLUS_THRESHOLD)
        if n > 0:
            sell_n = dynamic_sell_quantity(n, market_prices.get(item, BASE_PRICE.get(item, 0)), item, day=day)
            if sell_n > 0:
                market.append(["SELL", item, sell_n])
    # Generalized throttled sell for every high-glut-risk good (was
    # milk-only; melon needed the same treatment - above_target 3.60,
    # even worse than milk's 1.60 - so this now covers both from one
    # table instead of duplicating the same pattern per-item). Caps are
    # now price-aware (Day 17) instead of flat - see dynamic_sell_quantity.
    for item, cap in SELL_CAP_PER_TURN.items():
        n = shed.get(item, 0)
        if n > 0:
            sell_n = dynamic_sell_quantity(n, market_prices.get(item, BASE_PRICE.get(item, 0)), item, day=day, base_cap=cap)
            if sell_n > 0:
                market.append(["SELL", item, sell_n])

    # --- buy seed for whichever crop we're out of, cheapest first ---
    # Do not buy crops if they won't mature before the end of the 30-day season (day 29 is the last day)
    can_plant_for_buy = {
        "STRAWBERRY": day <= 19,
        "MELON": day <= 21,
        "WHEAT": day <= 25,
        "CARROT": day <= 26
    }
    for crop in CROP_PRIORITY:
        if not can_plant_for_buy.get(crop, False):
            continue
            
        target = float('inf')
        if crop == "STRAWBERRY":
            target = get_strawberry_target(unlocked_quadrants, market_prices)
        elif crop == "MELON":
            target = get_melon_target(unlocked_quadrants, market_prices)
            
        if plant_counts.get(crop, 0) + seeds.get(crop, 0) >= target:
            continue
            
        cost = CROP_SEED_COST[crop]
        if seeds.get(crop, 0) == 0 and money - dynamic_cash_reserve(unlocked_quadrants) >= cost:
            affordable = int((money - dynamic_cash_reserve(unlocked_quadrants)) // cost)
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
    fertilizer_cost = market_prices.get("FERTILIZER", FERTILIZER_COST)
    if shed.get("FERTILIZER", 0) == 0 and money - dynamic_cash_reserve(unlocked_quadrants) >= fertilizer_cost:
        market.append(["BUY_PRODUCT", "FERTILIZER", 1])
        money -= fertilizer_cost

    # --- hire hands at the start of the day if we can afford it. Target
    #     scales with owned land (crop_target = crop_hand_target(...))
    #     instead of a fixed number, so a farm with 2 quadrants hires
    #     enough crop hands for 2 quadrants' worth of work, not the same
    #     count that only ever matched a single quadrant. ---
    hires_today = me.get("hires_today", 0)
    current_hands = len(me.get("hands", []))
    # Calculate actual work waiting today to scale labor down during winter
    today_work_items = 0
    for y in range(board_size):
        for x in range(board_size):
            tile = tiles[y][x]
            if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                # Count if ready to harvest OR eligible for fertilizer (even if we don't have fertilizer yet,
                # because we will likely buy it this turn)
                if is_ready_to_harvest(tile, day) or is_fertilize_eligible(tile, day, for_purchase=True):
                    today_work_items += 1

    hand_target = total_hand_target(unlocked_quadrants)
    # Allow hiring at any hour to bypass the 10 market orders/turn cap
    while current_hands < hand_target and hires_today < len(HIRE_COST_SEQUENCE):
        cost = HIRE_COST_SEQUENCE[hires_today]
        if money < cost:
            break
        # Also respect the 10 market orders per turn limit ourselves so we don't truncate
        if len(market) >= 9:
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
    if hour == 23 and current_hands >= hand_target:
        land_idx = len(unlocked_quadrants) - 1
        if 0 <= land_idx < len(LAND_COST_SEQUENCE):
            land_cost = LAND_COST_SEQUENCE[land_idx]
            if money - dynamic_cash_reserve(unlocked_quadrants + ['DUMMY']) >= land_cost:
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
            skip_tiles=build_targets_this_turn, unlocked_quadrants=unlocked_quadrants
        )
        if order:
            market.append(order)
            if order[0] == "BUY_ANIMAL":
                money -= ANIMAL_COST[order[1]]
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
    fertilizer_n = shed.get("FERTILIZER", 0)
    targets = find_targets(tiles, board_size, day, seed_capacity, fertilizer_n)
    assignments = assign_targets(crop_positions, targets)

    remaining_seeds = dict(seeds)
    remaining_fertilizer = [fertilizer_n]  # mutable single-element list, shared
                                            # across units so a second unit
                                            # can't apply fertilizer we no
                                            # longer have this turn
    actions = [None] * len(positions)
    for list_i, unit_i in enumerate(crop_unit_indices):
        actions[unit_i] = decide_crop_action(
            positions[unit_i], tiles, day, remaining_seeds, assignments[list_i],
            remaining_fertilizer, plant_counts, unlocked_quadrants, market_prices
        )

    for slot, action in handler_slots.items():
        actions[slot] = action

    return {
        "farmer": actions[0],
        "hands": actions[1:],
        "market": market,
    }
