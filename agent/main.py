"""
Kaggriculture agent - Day 6.

New since Day 1-5:
  1. Hires up to TARGET_HAND_COUNT farm hands once cash allows, so more
     than one tile is being worked per turn (a single farmer was the
     bottleneck - hands are cheap early, Fibonacci pricing resets daily).
  2. Adds CARROT as a second crop alongside WHEAT (similar payback
     profile, diversifies away from a single price curve).
  3. Coordinates all units (farmer + hands) in one pass per turn: builds
     a shared task list (water > harvest > plant), assigns each unit its
     nearest unclaimed task, and tracks a local seed budget so two units
     never both try to plant the last seed in the same turn (the game
     silently discards BOTH plant actions if that happens - see spec:
     "If you try to plant too many in a specific turn, none are
     planted").

Still not doing: animals, land expansion, fertilizer, melon/premium
crops, throttled selling. Those come once this labor-scaling loop is
proven stable.
"""

BOARD_SIZE = 10
SEED_BUFFER = 200          # cash kept in reserve before buying seed
HAND_CASH_RESERVE = 300    # cash kept in reserve before hiring a hand
TARGET_HAND_COUNT = 2      # ramp slowly - more hands only help if fed with tasks

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


def find_targets(tiles, board_size, day, seed_capacity):
    """Scan owned (non-LOCKED) tiles for work. Returns a priority-ordered
    list of (x, y): unwatered plants first, then mature harvestable
    plants, then empty tiles (capped at how many seeds we actually have,
    so we never send a unit to an empty tile with nothing to plant)."""
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


def decide_unit_action(pos, tiles, day, remaining_seeds, target):
    """Decide one unit's action. Mutates remaining_seeds if it plants,
    so the next unit processed this turn sees an accurate seed budget."""
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

    market = []

    # --- sell everything sellable in the shed (wheat & carrot both have
    #     low/medium glut risk - safe to bulk sell, see economics.py) ---
    for crop in ("WHEAT", "CARROT"):
        n = shed.get(crop, 0)
        if n > 0:
            market.append(["SELL", crop, n])

    # --- buy seed for whichever crop we're out of, cheapest first ---
    for crop in CROP_PRIORITY:
        cost = CROP_SEED_COST[crop]
        if seeds.get(crop, 0) == 0 and money - SEED_BUFFER >= cost:
            affordable = int((money - SEED_BUFFER) // cost)
            buy_n = max(1, min(affordable, 10))
            market.append(["BUY_SEED", crop, buy_n])
            money -= buy_n * cost  # keep local money estimate consistent
            seeds[crop] = seeds.get(crop, 0) + buy_n
            break  # one seed purchase per turn keeps this predictable

    # --- hire hands at the start of the day if we can afford it and
    #     haven't hit our target headcount yet ---
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
            current_hands += 1  # hired hand won't appear until next turn's
                                 # obs, but track locally to avoid over-hiring

    # --- coordinate farmer + hands on tasks ---
    positions = [me["farmer"]] + list(me["hands"])
    seed_capacity = sum(seeds.values())
    targets = find_targets(tiles, board_size, day, seed_capacity)
    assignments = assign_targets(positions, targets)

    remaining_seeds = dict(seeds)
    actions = [
        decide_unit_action(positions[i], tiles, day, remaining_seeds, assignments[i])
        for i in range(len(positions))
    ]

    return {
        "farmer": actions[0],
        "hands": actions[1:],
        "market": market,
    }
