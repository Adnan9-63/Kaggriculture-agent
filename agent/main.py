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
TARGET_CROP_HAND_COUNT = 3   # farmer + these 3 = 4 crop workers, tested as the
                              # sweet spot for the 25-tile NW quadrant (see
                              # Day 12 decisions log)
TARGET_HAND_COUNT = TARGET_CROP_HAND_COUNT + 2   # +1 goose handler, +1 cow handler

CROP_SEED_COST = {"WHEAT": 10, "CARROT": 20}
# "Time to Max Yield" for one-time crops, unfertilized (from the spec
# table). Harvesting before this age locks in a smaller yield than
# waiting, since the tile clears on harvest - no second chance.
CROP_MATURITY_DAY = {"WHEAT": 4, "CARROT": 3}
# Order to prefer when planting - wheat first (cheaper, faster payback).
CROP_PRIORITY = ["WHEAT", "CARROT"]

# Fibonacci-ish hire cost sequence, indexed by hires_today (0-indexed).
# Matches farmHandCostMult(=1) * fib(n), fib starting 1,1,2,3,5,8,...
HIRE_COST_SEQUENCE = [1, 1, 2, 3, 5, 8, 13, 21, 34]

ANIMAL_COST = {"GOOSE": 300, "COW": 400}
ANIMAL_CASH_RESERVE = 300  # keep this much in reserve before buying an animal

TARGET_ANIMAL_HAND_COUNT = 2  # 1 for goose, 1 for cow - added on top of crop hands

# Milk has high glut risk (above_target=1.60 per economics.py) - unlike
# wheat/carrot/egg, dumping the whole shed at once would crash its own
# price hard. Cap how much sells per turn instead.
MILK_SELL_CAP_PER_TURN = 3

# Costs increase for each quadrant beyond the starting NW one - per spec:
# "$1k, $2k, $4k".
#
# DISABLED for now (empty list). Tested capped at 1 extra quadrant and it
# looked like a net win in tests/full_harness.py (14,230 vs 13,535 with
# no land) - but that local simulator uses flat pricing and doesn't spawn
# weeds at all. Against the REAL engine (tests/diagnostic_test.py, same
# fixed seed as the no-land goose version), it was a real regression:
# $7,090 vs $9,621, reproduced identically twice. Real cause, most likely:
# more owned tiles means more weed-spawn opportunities per day (each
# empty tile spawns a weed independently), and the NE quadrant is
# genuinely farther from the shed hub, so units spend more time
# traveling and less time watering/harvesting - exactly the labor
# bottleneck the strategy doc warned about, which my local simulator
# couldn't see. Revisit only once crop-worker count scales up enough to
# actually absorb the extra distance and weed-cleanup load.
LAND_COST_SEQUENCE = []
LAND_CASH_RESERVE = 500


def is_ready_to_harvest(tile, day):
    crop = tile.get("crop")
    maturity = CROP_MATURITY_DAY.get(crop, 0)
    age = day - tile.get("planted_day", day)
    return tile.get("yield_units", 0) > 0 and age >= maturity


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


def find_structure(tiles, board_size, kind):
    """Return (x, y) of the first structure tile of the given kind
    (COOP or PASTURE) found, or None."""
    for y in range(board_size):
        for x in range(board_size):
            tile = tiles[y][x]
            if isinstance(tile, dict) and tile.get("kind") == kind:
                return (x, y)
    return None


def find_empty_tile_from_corner(tiles, board_size, skip=None):
    """Scan for an empty tile starting from the bottom-right corner -
    crop planting scans from top-left, so this reduces (but doesn't
    fully eliminate) projects racing for the same tile. `skip` excludes
    a tile already claimed by another project this same turn (e.g. the
    goose's coop, when the cow handler is also hunting for space)."""
    for y in range(board_size - 1, -1, -1):
        for x in range(board_size - 1, -1, -1):
            if tiles[y][x] is None and (x, y) != skip:
                return (x, y)
    return None


def animal_handler_action(pos, tiles, board_size, money, shed, my_inventory,
                           animal, structure_kind, build_action, skip_tile=None):
    """Decide a dedicated handler's action for an animal project this
    turn (goose/coop or cow/pasture - same shape either way). Returns
    (action_list, market_order_or_None, is_busy, build_target_or_None).
    build_target is only set while still hunting for a spot to build on
    (before the structure exists) - the caller passes it as skip_tile to
    a second handler running the same turn, so two handlers never race
    to build on the exact same empty tile before either action lands."""
    structure_pos = find_structure(tiles, board_size, structure_kind)

    if structure_pos is None:
        target = find_empty_tile_from_corner(tiles, board_size, skip=skip_tile)
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

        # nothing in shed yet - try to buy one, handler free to farm meanwhile
        order = None
        if money - ANIMAL_CASH_RESERVE >= ANIMAL_COST[animal]:
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


def find_targets(tiles, board_size, day, seed_capacity):
    """Scan owned (non-LOCKED) tiles for crop work. Returns a
    priority-ordered list of (x, y): unwatered plants first, then mature
    harvestable plants, then empty tiles (capped at seeds on hand)."""
    water_targets, harvest_targets, empty_targets = [], [], []
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
            elif tile is None:
                empty_targets.append((x, y))
    return water_targets + harvest_targets + empty_targets[:seed_capacity]


def assign_targets(positions, targets):
    """Greedy nearest-target assignment, one target per unit, no repeats."""
    remaining = list(targets)
    assignments = []
    for pos in positions:
        if not remaining:
            assignments.append(None)
            continue
        best_i = min(
            range(len(remaining)),
            key=lambda i: abs(remaining[i][0] - pos[0]) + abs(remaining[i][1] - pos[1]),
        )
        assignments.append(remaining.pop(best_i))
    return assignments


def decide_crop_action(pos, tiles, day, remaining_seeds, target):
    x, y = pos
    tile = tiles[y][x]

    if isinstance(tile, dict) and tile.get("kind") == "PLANT":
        if not tile.get("watered_today"):
            return ["WATER"]
        if is_ready_to_harvest(tile, day):
            return ["HARVEST"]

    if isinstance(tile, dict) and tile.get("kind") == "WEED":
        return ["DIG"]

    if tile is None:
        for crop in CROP_PRIORITY:
            if remaining_seeds.get(crop, 0) > 0:
                remaining_seeds[crop] -= 1
                return ["PLANT", crop]

    if target is not None and target != (x, y):
        move = step_toward((x, y), target)
        if move:
            return [move]

    return ["PASS"]


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

    market = []

    # --- sell: wheat/carrot/egg have low/medium glut risk, bulk-sell is
    #     safe (see economics.py). Milk is HIGH glut risk (above_target
    #     1.60) - dumping the whole shed at once would crash its own
    #     price, so cap how much sells per turn instead. ---
    for item in ("WHEAT", "CARROT", "EGG"):
        n = shed.get(item, 0)
        if n > 0:
            market.append(["SELL", item, n])
    milk_n = shed.get("MILK", 0)
    if milk_n > 0:
        market.append(["SELL", "MILK", min(milk_n, MILK_SELL_CAP_PER_TURN)])

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

    # --- hire hands at the start of the day if we can afford it ---
    hires_today = me.get("hires_today", 0)
    current_hands = len(me.get("hands", []))
    if hour == 0:
        while current_hands < TARGET_HAND_COUNT and hires_today < len(HIRE_COST_SEQUENCE):
            cost = HIRE_COST_SEQUENCE[hires_today]
            if money - HAND_CASH_RESERVE < cost:
                break
            market.append(["HIRE"])
            money -= cost
            hires_today += 1
            current_hands += 1

    # --- buy land once fully staffed and cash allows - expanding before
    #     labor exists just leaves new tiles idle ---
    unlocked_quadrants = me.get("unlocked_quadrants", ["NW"])
    if hour == 0 and current_hands >= TARGET_HAND_COUNT:
        land_idx = len(unlocked_quadrants) - 1
        if 0 <= land_idx < len(LAND_COST_SEQUENCE):
            land_cost = LAND_COST_SEQUENCE[land_idx]
            if money - LAND_CASH_RESERVE >= land_cost:
                market.append(["BUY_LAND"])
                money -= land_cost

    # --- positions: farmer first, then hands. Handlers are the LAST 2
    #     hands - the goose handler, then the cow handler - and only
    #     once ALL target hands are hired. The farmer and first
    #     TARGET_CROP_HAND_COUNT hands must never be pulled off crop
    #     duty. Testing (Day 7-10) showed a large regression when an
    #     existing crop hand got reassigned instead: cut real crop-tile
    #     coverage by a third, and the animal's daily feed requirement
    #     pulled that hand back every day for the rest of the game - a
    #     bad trade for one animal's income. ---
    positions = [me["farmer"]] + list(me["hands"])
    goose_slot = TARGET_CROP_HAND_COUNT + 1
    cow_slot = TARGET_CROP_HAND_COUNT + 2

    handler_slots_busy = {}  # slot index -> (action_list,) for busy handlers
    goose_build_target = None

    if len(positions) > goose_slot:
        pos = positions[goose_slot]
        inv = inventories[goose_slot] if goose_slot < len(inventories) else {}
        action, order, busy, build_target = animal_handler_action(
            pos, tiles, board_size, money, shed, inv,
            animal="GOOSE", structure_kind="COOP", build_action="BUILD_COOP",
        )
        if order:
            market.append(order)
        if busy:
            handler_slots_busy[goose_slot] = action
        goose_build_target = build_target

    if len(positions) > cow_slot:
        pos = positions[cow_slot]
        inv = inventories[cow_slot] if cow_slot < len(inventories) else {}
        action, order, busy, _ = animal_handler_action(
            pos, tiles, board_size, money, shed, inv,
            animal="COW", structure_kind="PASTURE", build_action="BUILD_PASTURE",
            skip_tile=goose_build_target,
        )
        if order:
            market.append(order)
        if busy:
            handler_slots_busy[cow_slot] = action

    # --- coordinate remaining (non-handler-busy) units on crop tasks ---
    crop_unit_indices = [i for i in range(len(positions)) if i not in handler_slots_busy]
    crop_positions = [positions[i] for i in crop_unit_indices]

    seed_capacity = sum(seeds.values())
    targets = find_targets(tiles, board_size, day, seed_capacity)
    assignments = assign_targets(crop_positions, targets)

    remaining_seeds = dict(seeds)
    actions = [None] * len(positions)
    for list_i, unit_i in enumerate(crop_unit_indices):
        actions[unit_i] = decide_crop_action(
            positions[unit_i], tiles, day, remaining_seeds, assignments[list_i]
        )

    for slot, action in handler_slots_busy.items():
        actions[slot] = action

    return {
        "farmer": actions[0],
        "hands": actions[1:],
        "market": market,
    }
