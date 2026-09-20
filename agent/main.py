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


def get_wheat_target(total_owned_animals):
    return max(10, int((total_owned_animals + 3) / 1.5) + 2)

def total_hand_target(unlocked_quadrants):
    return min(16, 4 + len(unlocked_quadrants) * 3)

def dynamic_cash_reserve(unlocked_quadrants, hands_count=0, for_land=False):
    hand_target = total_hand_target(unlocked_quadrants)
    daily_hire_cost = sum(HIRE_COST_SEQUENCE[:hand_target])
    if for_land:
        return daily_hire_cost * 3 + len(unlocked_quadrants) * 300
    return daily_hire_cost + 100

CROP_SEED_COST = {"WHEAT": 10, "CARROT": 20, "MELON": 80, "STRAWBERRY": 100}
CROP_MATURITY_DAY = {"WHEAT": 4, "CARROT": 3, "MELON": 10, "STRAWBERRY": 10}
CROP_PRIORITY = ["WHEAT", "STRAWBERRY", "MELON", "CARROT"]
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


def get_carrot_target(unlocked_quadrants, prices):
    target = 10
    if prices.get("CARROT", 35) > 40:
        target = 20
    elif prices.get("CARROT", 35) < 25:
        target = 5
    return target * max(1, len(unlocked_quadrants))


MIN_WHEAT_TILES_BEFORE_MELON = 4

FERTILIZE_ELIGIBLE_CROPS = {"MELON", "STRAWBERRY"}
SURPLUS_ELIGIBLE_CROPS = set()
FERTILIZER_SURPLUS_THRESHOLD = 0
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


def choose_crop_to_plant(remaining_seeds, plant_counts, unlocked_quadrants, day, prices, total_owned_animals):
    target_strawberry = get_strawberry_target(unlocked_quadrants, prices)
    target_melon = get_melon_target(unlocked_quadrants, prices)
    target_carrot = get_carrot_target(unlocked_quadrants, prices)
    wheat_established = plant_counts.get("WHEAT", 0) >= get_wheat_target(total_owned_animals)
    
    can_plant = {
        "STRAWBERRY": day <= 19,
        "MELON": day <= 21,
        "WHEAT": day <= 25,
        "CARROT": day <= 26
    }
    
    targets = {
        "STRAWBERRY": target_strawberry,
        "MELON": target_melon,
        "CARROT": target_carrot,
        "WHEAT": float('inf')
    }

    # First pass: Respect targets and wheat requirement
    for crop in CROP_PRIORITY:
        if not can_plant.get(crop, False):
            continue
        if crop in ("STRAWBERRY", "MELON", "CARROT") and not wheat_established:
            continue
        if remaining_seeds.get(crop, 0) > 0 and plant_counts.get(crop, 0) < targets[crop]:
            return crop

    # Second pass: Fallback if targets are met but we have seeds and empty tiles
    for crop in CROP_PRIORITY:
        if not can_plant.get(crop, False):
            continue
        if crop in ("STRAWBERRY", "MELON", "CARROT") and not wheat_established:
            continue
        if remaining_seeds.get(crop, 0) > 0:
            return crop

    return None

def count_placed_animals(tiles, board_size):

    count = 0
    for y in range(board_size):
        for x in range(board_size):
            tile = tiles[y][x]
            if isinstance(tile, dict) and tile.get("kind") in ("COOP", "PASTURE") and tile.get("animal"):
                count += 1
    return count

def count_plant_tiles_by_crop(tiles, board_size):

    counts = {}
    for y in range(board_size):
        for x in range(board_size):
            tile = tiles[y][x]
            if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                crop = tile.get("crop")
                counts[crop] = counts.get(crop, 0) + 1
    return counts

def find_targets(tiles, board_size, day, seed_capacity, shed, private):
    starving_animal = []
    water_targets = []
    harvest_animal = []
    harvest_targets = []
    care_animal = []
    unplaced_animal = []
    build_structure = []
    empty_targets = []
    
    unplaced_counts = {
        "GOOSE": shed.get("GOOSE", 0),
        "COW": shed.get("COW", 0),
        "SHEEP": shed.get("SHEEP", 0)
    }
    for inv in private.get("inventories", []):
        for k in unplaced_counts:
            unplaced_counts[k] += inv.get(k, 0)
            
    needed_structures = {
        "COOP": unplaced_counts["GOOSE"],
        "PASTURE": unplaced_counts["COW"] + unplaced_counts["SHEEP"]
    }
    
    empty_structure_counts = {"COOP": 0, "PASTURE": 0}

    for y in range(board_size):
        for x in range(board_size):
            tile = tiles[y][x]
            if tile == "LOCKED":
                continue
            
            if isinstance(tile, dict):
                kind = tile.get("kind")
                if kind == "PLANT":
                    if not tile.get("watered_today"):
                        water_targets.append((x, y))
                    elif is_ready_to_harvest(tile, day):
                        harvest_targets.append((x, y))
                elif kind in ("COOP", "PASTURE"):
                    animal = tile.get("animal")
                    if animal:
                        if not tile.get("fed_today"):
                            starving_animal.append((x, y))
                        elif tile.get("yield_units", 0) > 0:
                            harvest_animal.append((x, y))
                        elif not tile.get("cared_today"):
                            care_animal.append((x, y))
                    else:
                        unplaced_animal.append((x, y))
                        empty_structure_counts[kind] += 1
            elif tile is None:
                empty_targets.append((x, y))
                
    build_targets_needed = max(0, needed_structures["COOP"] - empty_structure_counts["COOP"]) + max(0, needed_structures["PASTURE"] - empty_structure_counts["PASTURE"])
    if build_targets_needed > 0 and empty_targets:
        build_structure = empty_targets[-min(len(empty_targets), build_targets_needed):]
        empty_targets = empty_targets[:-len(build_structure)]
        
    # If we need wheat, prioritize planting it over almost everything else
    plant_counts = {}
    for y in range(board_size):
        for x in range(board_size):
            tile = tiles[y][x]
            if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                crop = tile.get("crop")
                plant_counts[crop] = plant_counts.get(crop, 0) + 1
    
    # We don't have total_owned_animals exactly here, so we approximate it using unplaced_counts + shedding animals
    # Wait, unplaced_counts already has all unplaced animals.
    total_animals_approx = sum(unplaced_counts.values()) 
    for y in range(board_size):
        for x in range(board_size):
            tile = tiles[y][x]
            if isinstance(tile, dict) and tile.get("kind") in ("COOP", "PASTURE") and tile.get("animal"):
                total_animals_approx += 1
                
    needed_wheat = max(4, total_animals_approx + 1) - plant_counts.get("WHEAT", 0)
    critical_wheat = []
    if needed_wheat > 0 and empty_targets and private.get("seeds", {}).get("WHEAT", 0) > 0:
        take = min(needed_wheat, private.get("seeds", {}).get("WHEAT", 0), len(empty_targets))
        critical_wheat = empty_targets[:take]
        empty_targets = empty_targets[take:]
        
    return [starving_animal, critical_wheat, water_targets, harvest_animal, harvest_targets, care_animal, unplaced_animal, build_structure, empty_targets[:seed_capacity]]


def assign_targets(positions, tiers, inventories, tiles):
    # inventories is a list of dicts for each hand
    tiers = [list(t) for t in tiers]
    assignments = [None] * len(positions)
    
    # Pre-assign hands that are holding items to tasks that need those items
    # Items: COW, SHEEP, GOOSE, WHEAT
    
    available_hands = list(range(len(positions)))
    
    # 1. Match hands holding Animals to Empty Pastures/Coops (tier 6 in find_targets, wait... tier 6 is unplaced_animal)
    if len(tiers) > 6:
        unplaced_tier = tiers[6]
        for h in list(available_hands):
            inv = inventories[h] if h < len(inventories) else {}
            held_animal = None
            if inv.get("COW", 0) > 0: held_animal = "COW"
            elif inv.get("SHEEP", 0) > 0: held_animal = "SHEEP"
            elif inv.get("GOOSE", 0) > 0: held_animal = "GOOSE"
            
            if held_animal and unplaced_tier:
                best_i = -1
                best_dist = 9999
                for i, target in enumerate(unplaced_tier):
                    target_tile = tiles[target[1]][target[0]]
                    if isinstance(target_tile, dict) and not target_tile.get("animal"):
                        kind = target_tile.get("kind")
                        if (kind == "PASTURE" and held_animal in ("COW", "SHEEP")) or (kind == "COOP" and held_animal == "GOOSE"):
                            dist = abs(target[0] - positions[h][0]) + abs(target[1] - positions[h][1])
                            if dist < best_dist:
                                best_dist = dist
                                best_i = i
                if best_i != -1:
                    assignments[h] = unplaced_tier.pop(best_i)
                    available_hands.remove(h)
                    
    # 2. Match hands holding Wheat to Starving Animals (tier 0)
    if len(tiers) > 0:
        starving_tier = tiers[0]
        for h in list(available_hands):
            inv = inventories[h] if h < len(inventories) else {}
            if inv.get("WHEAT", 0) > 0 and starving_tier:
                best_i = min(range(len(starving_tier)), key=lambda i: abs(starving_tier[i][0] - positions[h][0]) + abs(starving_tier[i][1] - positions[h][1]))
                assignments[h] = starving_tier.pop(best_i)
                available_hands.remove(h)

    # 3. Greedy assignment for the rest (Target-Priority)
    shed_pos = (len(tiles[0]) // 2, len(tiles) // 2) if len(tiles) > 0 else (0, 0)
    for tier_idx, tier in enumerate(tiers):
        for target in tier:
            if not available_hands:
                break
            
            # Find the best hand for this target
            if tier_idx in (0, 6):
                # Needs fetching from shed, minimize hand->shed distance
                best_h = min(
                    available_hands,
                    key=lambda h: abs(shed_pos[0] - positions[h][0]) + abs(shed_pos[1] - positions[h][1])
                )
            else:
                # Direct task, minimize hand->target distance
                best_h = min(
                    available_hands,
                    key=lambda h: abs(target[0] - positions[h][0]) + abs(target[1] - positions[h][1])
                )
                
            assignments[best_h] = target
            available_hands.remove(best_h)
        if not available_hands:
            break
        
    return assignments

def decide_action(pos, tiles, board_size, day, remaining_seeds, target, plant_counts, unlocked_quadrants, market_prices, my_inventory, unplaced_counts, needed_structures, empty_structure_counts, shed, total_owned_animals):
    if target is None:
        return ["PASS"]
        
    x, y = pos
    tile = tiles[y][x]

    if isinstance(tile, dict):
        kind = tile.get("kind")
        if kind == "PLANT":
            if not tile.get("watered_today"):
                return ["WATER"]
            if is_ready_to_harvest(tile, day):
                return ["HARVEST"]
        elif kind in ("COOP", "PASTURE"):
            animal = tile.get("animal")
            if animal:
                if not tile.get("fed_today"):
                    if my_inventory.get("WHEAT", 0) > 0:
                        if tuple(pos) == target:
                            return ["FEED"]
                        else:
                            move = step_toward(pos, target)
                            return [move] if move else ["PASS"]
                    else:
                        target = nearest(pos, shed_adjacent_positions(board_size))
                        if tuple(pos) == target:
                            if shed.get("WHEAT", 0) > 0:
                                shed["WHEAT"] -= 1
                                return ["PICKUP", "WHEAT", 5]
                            return ["PASS"]
                        move = step_toward(pos, target)
                        return [move] if move else ["PASS"]
                if tile.get("yield_units", 0) > 0:
                    return ["HARVEST"]
                if not tile.get("cared_today"):
                    return ["CARE"]
            else:
                if kind == "COOP":
                    if my_inventory.get("GOOSE", 0) > 0:
                        if tuple(pos) == target:
                            return ["PLACE", "GOOSE"]
                        else:
                            move = step_toward(pos, target)
                            return [move] if move else ["PASS"]
                    elif unplaced_counts["GOOSE"] > 0:
                        target = nearest(pos, shed_adjacent_positions(board_size))
                        if tuple(pos) == target:
                            if shed.get("GOOSE", 0) > 0:
                                shed["GOOSE"] -= 1
                                return ["PICKUP", "GOOSE", 1]
                            return ["PASS"]
                        move = step_toward(pos, target)
                        return [move] if move else ["PASS"]
                elif kind == "PASTURE":
                    if my_inventory.get("COW", 0) > 0:
                        if tuple(pos) == target:
                            return ["PLACE", "COW"]
                        else:
                            move = step_toward(pos, target)
                            return [move] if move else ["PASS"]
                    elif my_inventory.get("SHEEP", 0) > 0:
                        if tuple(pos) == target:
                            return ["PLACE", "SHEEP"]
                        else:
                            move = step_toward(pos, target)
                            return [move] if move else ["PASS"]
                    elif unplaced_counts["COW"] > 0 or unplaced_counts["SHEEP"] > 0:
                        target = nearest(pos, shed_adjacent_positions(board_size))
                        if tuple(pos) == target:
                            if shed.get("COW", 0) > 0:
                                shed["COW"] -= 1
                                return ["PICKUP", "COW", 1]
                            elif shed.get("SHEEP", 0) > 0:
                                shed["SHEEP"] -= 1
                                return ["PICKUP", "SHEEP", 1]
                            return ["PASS"]
                        move = step_toward(pos, target)
                        return [move] if move else ["PASS"]

    if target is not None:
        target_tile = tiles[target[1]][target[0]]
        if target_tile is None:
            if tuple(pos) == target:
                crop = choose_crop_to_plant(remaining_seeds, plant_counts, unlocked_quadrants, day, market_prices, total_owned_animals)
                
                # If we critically need Wheat, plant it immediately instead of building structures
                if crop == "WHEAT":
                    remaining_seeds[crop] -= 1
                    return ["PLANT", crop]
                    
                if needed_structures["COOP"] > empty_structure_counts["COOP"]:
                    empty_structure_counts["COOP"] += 1
                    return ["BUILD_COOP"]
                elif needed_structures["PASTURE"] > empty_structure_counts["PASTURE"]:
                    empty_structure_counts["PASTURE"] += 1
                    return ["BUILD_PASTURE"]
                else:
                    if crop is not None:
                        remaining_seeds[crop] -= 1
                        return ["PLANT", crop]
                    return ["PASS"]
        elif isinstance(target_tile, dict) and target_tile.get("kind") in ("COOP", "PASTURE") and target_tile.get("animal") and not target_tile.get("fed_today"):
            if my_inventory.get("WHEAT", 0) == 0:
                target = nearest(pos, shed_adjacent_positions(board_size))
                if tuple(pos) == target:
                    if shed.get("WHEAT", 0) > 0:
                        shed["WHEAT"] -= 1
                        return ["PICKUP", "WHEAT", 5]
                    return ["PASS"]
        elif isinstance(target_tile, dict) and target_tile.get("kind") in ("COOP", "PASTURE") and not target_tile.get("animal"):
            if target_tile.get("kind") == "COOP":
                if my_inventory.get("GOOSE", 0) == 0:
                    target = nearest(pos, shed_adjacent_positions(board_size))
                    if tuple(pos) == target:
                        if shed.get("GOOSE", 0) > 0:
                            shed["GOOSE"] -= 1
                            return ["PICKUP", "GOOSE", 1]
                        return ["PASS"]
            elif target_tile.get("kind") == "PASTURE":
                if my_inventory.get("COW", 0) == 0 and my_inventory.get("SHEEP", 0) == 0:
                    target = nearest(pos, shed_adjacent_positions(board_size))
                    if tuple(pos) == target:
                        if shed.get("COW", 0) > 0:
                            shed["COW"] -= 1
                            return ["PICKUP", "COW", 1]
                        elif shed.get("SHEEP", 0) > 0:
                            shed["SHEEP"] -= 1
                            return ["PICKUP", "SHEEP", 1]
                        return ["PASS"]
        
        move = step_toward(pos, target)
        return [move] if move else ["PASS"]

    return ["PASS"]


agent_state = {}

def agent(obs):
    global agent_state


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

    pass
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
    total_owned_animals = count_placed_animals(tiles, board_size)
    for kind in ("GOOSE", "COW", "SHEEP"):
        total_owned_animals += shed.get(kind, 0)
        for inv in private.get("inventories", []):
            total_owned_animals += inv.get(kind, 0)
    total_owned_animals += agent_state.get("pending_animal_count", 0)
    have_handler_capacity = total_hand_target(unlocked_quadrants) > crop_target
    wheat_reserve = WHEAT_FEED_RESERVE_PER_ANIMAL * total_owned_animals
    if have_handler_capacity and day <= 20:
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
        target = 10  # Fallback target to maintain seed stock
        if crop == "STRAWBERRY":
            target = get_strawberry_target(unlocked_quadrants, market_prices)
        elif crop == "MELON":
            target = get_melon_target(unlocked_quadrants, market_prices)
        elif crop == "CARROT":
            target = get_carrot_target(unlocked_quadrants, market_prices)
        elif crop == "WHEAT":
            target = get_wheat_target(total_owned_animals)
            
        if plant_counts.get(crop, 0) + seeds.get(crop, 0) >= target:
            continue
            
        cost = CROP_SEED_COST[crop]
        available_money_for_seed = money - agent_state.get("pending_seed_cost", 0) - agent_state.get("pending_animal_cost", 0) - agent_state.get("pending_hire_cost", 0) - agent_state.get("pending_land_cost", 0)
        if seeds.get(crop, 0) < target and money - dynamic_cash_reserve(unlocked_quadrants, len(me.get("hands", []))) >= cost:
            affordable = int((money - dynamic_cash_reserve(unlocked_quadrants, len(me.get("hands", [])))) // cost)
            # Only buy up to what we need to hit the target, capped at 10
            needed = target - (plant_counts.get(crop, 0) + seeds.get(crop, 0))
            buy_n = max(1, min(affordable, min(10, needed)))
            market.append(["BUY_SEED", crop, buy_n])
            money -= buy_n * cost
            seeds[crop] = seeds.get(crop, 0) + buy_n
            break


    # BUY_PRODUCT FERTILIZER logic was removed to prevent worker paralysis

    if hour == 23 and len(me.get("hands", [])) >= total_hand_target(unlocked_quadrants):
        land_idx = len(unlocked_quadrants) - 1
        if 0 <= land_idx < len(LAND_COST_SEQUENCE):
            land_cost = LAND_COST_SEQUENCE[land_idx]
            if money - dynamic_cash_reserve(unlocked_quadrants + ['DUMMY'], len(me.get("hands", [])), for_land=True) >= land_cost:
                market.append(["BUY_LAND"])
                money -= land_cost

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
    
    unplaced_counts = {
        "GOOSE": shed.get("GOOSE", 0),
        "COW": shed.get("COW", 0),
        "SHEEP": shed.get("SHEEP", 0)
    }
    for inv in inventories:
        for k in unplaced_counts:
            unplaced_counts[k] += inv.get(k, 0)
            
    needed_structures = {
        "COOP": unplaced_counts["GOOSE"],
        "PASTURE": unplaced_counts["COW"] + unplaced_counts["SHEEP"]
    }
    empty_structure_counts = {"COOP": 0, "PASTURE": 0}
    
    seed_capacity = sum(seeds.values())
    targets = find_targets(tiles, board_size, day, seed_capacity, shed, private)
    # --- buy animals ---
    # We want to mass-scale animals (Cow).
    # Cows cost $400, take 8 days for first yield (6 Milk = $960), then 3 Milk every 2 days.
    # MUST buy before Day 20 to get any yield!
    if total_owned_animals < 30 and day <= 24:
        # Only buy Cow if we have enough above the safety reserve.
        # dynamic_cash_reserve already protects seeds + labor costs.
        # Add extra $200 buffer per unplaced cow to leave room for WHEAT purchases.
        cow_budget = money - dynamic_cash_reserve(unlocked_quadrants, len(me.get("hands", [])))
        if cow_budget >= ANIMAL_COST.get("COW", 400):
            market.append(["BUY_ANIMAL", "COW", 1])
            money -= ANIMAL_COST.get("COW", 400)
            total_owned_animals += 1
            unplaced_counts["COW"] += 1
            if shed.get("WHEAT", 0) > 0:
                shed["WHEAT"] -= 1

    assignments = assign_targets(positions, targets, inventories, tiles)

    remaining_seeds = dict(seeds)
    actions = [None] * len(positions)
    for i, pos in enumerate(positions):
        my_inv = inventories[i] if i < len(inventories) else {}
        actions[i] = decide_action(
            pos, tiles, board_size, day, remaining_seeds, assignments[i],
            plant_counts, unlocked_quadrants, market_prices, my_inv,
            unplaced_counts, needed_structures, empty_structure_counts, shed, total_owned_animals
        )

    return {
        "farmer": actions[0],
        "hands": actions[1:],
        "market": market,
    }
