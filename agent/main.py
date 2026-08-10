"""
Kaggriculture agent - Day 1 baseline.

Strategy (deliberately simple, correctness over cleverness):
  1. SAFETY FIRST: never let an owned plant go unwatered, never let an
     owned animal go unfed. This alone avoids the most common way new
     bots bleed money.
  2. Single farmer runs a scan-and-farm loop over owned tiles: water /
     harvest what's there, plant wheat on empty tiles.
  3. Sell wheat from the shed every turn (wheat has low glut risk, safe
     to bulk sell - see agent/economics.py).
  4. Buy wheat seed when out and cash allows.

No hands, no animals, no land expansion, no melon/premium crops yet -
those come once this loop is proven stable. Better to submit something
reliable on day 1 than something ambitious and broken.
"""

WHEAT_SEED_COST = 10
SEED_BUFFER = 200  # keep this much cash in reserve before buying seeds
BOARD_SIZE = 10

# "Time to Max Yield" for one-time crops, unfertilized (from the spec table).
# Harvesting before this age locks in a much smaller yield than waiting -
# the tile is cleared on harvest for one-time crops, so there's no second
# chance. We only plant wheat right now, but this is written generically
# so adding carrot/melon later is a one-line change.
MATURITY_DAY = {"WHEAT": 4, "CARROT": 3, "MELON": 10}


def is_ready_to_harvest(tile, day):
    crop = tile.get("crop")
    maturity = MATURITY_DAY.get(crop, 0)
    age = day - tile.get("planted_day", day)
    return tile.get("yield_units", 0) > 0 and age >= maturity


def find_target(tiles, board_size, day):
    """Scan owned (non-LOCKED) tiles row-major, return the first tile that
    needs attention: a plant needing water, a mature plant ready to
    harvest, or an empty tile to plant on. Returns (x, y) or None."""
    best_empty = None
    for y in range(board_size):
        for x in range(board_size):
            tile = tiles[y][x]
            if tile == "LOCKED":
                continue
            if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                if not tile.get("watered_today"):
                    return (x, y)
                if is_ready_to_harvest(tile, day):
                    return (x, y)
            elif tile is None and best_empty is None:
                best_empty = (x, y)
    return best_empty


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


def unit_action(pos, tiles, seeds_wheat, board_size, day):
    x, y = pos
    tile = tiles[y][x]

    if isinstance(tile, dict) and tile.get("kind") == "PLANT":
        if not tile.get("watered_today"):
            return ["WATER"]
        if is_ready_to_harvest(tile, day):
            return ["HARVEST"]

    if tile is None and seeds_wheat > 0:
        return ["PLANT", "WHEAT"]

    if isinstance(tile, dict) and tile.get("kind") == "WEED":
        return ["DIG"]

    target = find_target(tiles, board_size, day)
    if target is None or target == (x, y):
        return ["PASS"]
    move = step_toward((x, y), target)
    return [move] if move else ["PASS"]


def agent(obs):
    player = obs["player"]
    me = obs["farms"][player]
    private = obs["private"]
    tiles = me["tiles"]
    board_size = len(tiles)

    money = me["money"]
    seeds_wheat = private["seeds"].get("WHEAT", 0)
    wheat_in_shed = private["shed"].get("WHEAT", 0)

    market = []

    # Sell any wheat sitting in the shed - low glut risk, safe to bulk sell.
    if wheat_in_shed > 0:
        market.append(["SELL", "WHEAT", wheat_in_shed])

    # Buy more wheat seed if we're out and can afford it comfortably.
    if seeds_wheat == 0 and money - SEED_BUFFER >= WHEAT_SEED_COST:
        affordable = int((money - SEED_BUFFER) // WHEAT_SEED_COST)
        buy_n = max(1, min(affordable, 10))
        market.append(["BUY_SEED", "WHEAT", buy_n])

    farmer_action = unit_action(me["farmer"], tiles, seeds_wheat, board_size, obs["day"])

    return {
        "farmer": farmer_action,
        "hands": [],
        "market": market,
    }
