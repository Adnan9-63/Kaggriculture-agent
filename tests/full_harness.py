"""
Fuller local simulator - unlike mock_harness.py (single farmer only),
this models hands, hiring, and the coop/animal mechanics well enough to
debug agent LOGIC (wasted turns, stuck units, contention for space) even
though pricing is still flat/approximate. Built specifically to
investigate the Day 7-10 regression without burning real-engine test
cycles on every guess.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))
from main import agent  # noqa: E402

BOARD_SIZE = 10
STARTING_MONEY = 3000
PRICES = {"WHEAT": 25, "CARROT": 35, "EGG": 50}
SEED_COST = {"WHEAT": 10, "CARROT": 20}
ANIMAL_COST = {"GOOSE": 300}
MATURITY = {"WHEAT": 4, "CARROT": 3}
CAP = {"WHEAT": 4, "CARROT": 3}
HIRE_COST_SEQUENCE = [1, 1, 2, 3, 5, 8, 13, 21, 34]


def make_board():
    tiles = [[None for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
    for y in range(BOARD_SIZE):
        for x in range(BOARD_SIZE):
            if x >= 5 or y >= 5:
                tiles[y][x] = "LOCKED"
    return tiles


def hand_spawn_pos(existing_hand_positions):
    """Simplified NWSE-preference spawn near the shed hub."""
    candidates = [(5, 4), (4, 3), (3, 4), (4, 5)]  # N,W,S,E of (4,4)-ish, simplified
    for c in candidates:
        if c not in existing_hand_positions:
            return list(c)
    return [4, 4]


def apply_movement(pos, act):
    x, y = pos
    if act == "NORTH":
        y = max(0, y - 1)
    elif act == "SOUTH":
        y = min(BOARD_SIZE - 1, y + 1)
    elif act == "EAST":
        x = min(BOARD_SIZE - 1, x + 1)
    elif act == "WEST":
        x = max(0, x - 1)
    return [x, y]


def run(turns=720, verbose=True, label=""):
    tiles = make_board()
    farmer = [4, 4]
    hands = []
    inventories = [{}]
    money = STARTING_MONEY
    shed = {}
    seeds = {}
    day = 0
    hires_today = 0
    unlocked_quadrants = ["NW"]
    LAND_COST_SEQUENCE = [1000, 2000, 4000]
    errors = []
    wasted_turns = 0  # PASS or a move that ends up not adjacent to any real task
    action_log = {}

    for turn in range(turns):
        hour = turn % 24
        positions = [farmer] + hands
        obs = {
            "player": 0, "day": day, "hour": hour,
            "farms": [{
                "money": money, "tiles": tiles, "farmer": farmer, "hands": hands,
                "unlocked_quadrants": unlocked_quadrants, "hires_today": hires_today,
            }],
            "market": {"inventory": {k: 10000 for k in PRICES}, "prices": dict(PRICES)},
            "town": {"unlocked_shops": []},
            "private": {"shed": shed, "seeds": seeds, "inventories": inventories},
        }

        try:
            result = agent(obs)
        except Exception as e:
            errors.append((turn, repr(e)))
            if verbose:
                print(f"[{label}] [turn {turn}] AGENT CRASHED: {e!r}")
            break

        # --- market orders ---
        for order in result.get("market", []):
            op = order[0]
            action_log[op] = action_log.get(op, 0) + 1
            if op == "SELL":
                _, item, n = order
                have = shed.get(item, 0)
                n = min(n, have)
                shed[item] = have - n
                money += n * PRICES.get(item, 0)
            elif op == "BUY_SEED":
                _, item, n = order
                cost = n * SEED_COST[item]
                if money >= cost:
                    money -= cost
                    seeds[item] = seeds.get(item, 0) + n
            elif op == "BUY_ANIMAL":
                _, item, n = order
                cost = n * ANIMAL_COST[item]
                if money >= cost:
                    money -= cost
                    shed[item] = shed.get(item, 0) + n
            elif op == "HIRE":
                cost = HIRE_COST_SEQUENCE[min(hires_today, len(HIRE_COST_SEQUENCE) - 1)]
                if money >= cost:
                    money -= cost
                    existing = [tuple(h) for h in hands]
                    hands.append(hand_spawn_pos(existing))
                    inventories.append({})
                    hires_today += 1
            elif op == "BUY_LAND":
                idx = len(unlocked_quadrants) - 1
                if 0 <= idx < len(LAND_COST_SEQUENCE):
                    cost = LAND_COST_SEQUENCE[idx]
                    if money >= cost:
                        money -= cost
                        next_quadrant = ["NE", "SW", "SE"][idx]
                        unlocked_quadrants.append(next_quadrant)
                        x0, x1 = (5, 10) if "E" in next_quadrant else (0, 5)
                        y0, y1 = (5, 10) if next_quadrant[0] == "S" else (0, 5)
                        for y in range(y0, y1):
                            for x in range(x0, x1):
                                if tiles[y][x] == "LOCKED":
                                    tiles[y][x] = None

        # --- unit actions ---
        all_units_actions = [result.get("farmer", ["PASS"])] + result.get("hands", [])
        for i in range(len(positions)):
            if i >= len(all_units_actions):
                continue
            pos = positions[i]
            act_list = all_units_actions[i]
            act = act_list[0] if act_list else "PASS"
            action_log[act] = action_log.get(act, 0) + 1
            x, y = pos
            tile = tiles[y][x] if 0 <= y < BOARD_SIZE and 0 <= x < BOARD_SIZE else "LOCKED"

            if act in ("NORTH", "SOUTH", "EAST", "WEST"):
                new_pos = apply_movement(pos, act)
                if i == 0:
                    farmer[:] = new_pos
                else:
                    hands[i - 1][:] = new_pos
            elif act == "WATER":
                if isinstance(tile, dict):
                    tile["watered_today"] = True
                else:
                    wasted_turns += 1
            elif act == "PLANT":
                crop = act_list[1]
                if seeds.get(crop, 0) > 0 and tile is None:
                    seeds[crop] -= 1
                    tiles[y][x] = {
                        "kind": "PLANT", "crop": crop, "planted_day": day,
                        "watered_today": False, "yield_units": 0,
                    }
                else:
                    wasted_turns += 1
            elif act == "HARVEST":
                if isinstance(tile, dict) and tile.get("kind") == "PLANT" and tile.get("yield_units", 0) > 0:
                    crop = tile["crop"]
                    shed[crop] = shed.get(crop, 0) + tile["yield_units"]
                    tiles[y][x] = None
                elif isinstance(tile, dict) and tile.get("kind") == "COOP" and tile.get("yield_units", 0) > 0:
                    shed["EGG"] = shed.get("EGG", 0) + tile["yield_units"]
                    tile["yield_units"] = 0
                else:
                    wasted_turns += 1
            elif act == "DIG":
                if isinstance(tile, dict) and tile.get("kind") == "WEED":
                    tiles[y][x] = None
                else:
                    wasted_turns += 1
            elif act == "BUILD_COOP":
                if tile is None:
                    tiles[y][x] = {
                        "kind": "COOP", "animal": None, "placed_day": day,
                        "yield_units": 0, "fed_today": False, "consecutive_unfed": 0,
                        "cared_today": False, "fertilizer_available": False,
                        "pending_care_bonus": 0,
                    }
                else:
                    wasted_turns += 1
            elif act == "PICKUP":
                item, n = act_list[1], act_list[2]
                have = shed.get(item, 0)
                n = min(n, have)
                if n > 0:
                    shed[item] = have - n
                    inventories[i][item] = inventories[i].get(item, 0) + n
                else:
                    wasted_turns += 1
            elif act == "PLACE":
                item = act_list[1]
                if inventories[i].get(item, 0) > 0 and isinstance(tile, dict) and tile.get("kind") == "COOP" and tile.get("animal") is None:
                    inventories[i][item] -= 1
                    tile["animal"] = item
                else:
                    wasted_turns += 1
            elif act == "FEED":
                if isinstance(tile, dict) and tile.get("kind") == "COOP" and tile.get("animal"):
                    tile["fed_today"] = True
                else:
                    wasted_turns += 1
            elif act == "CARE":
                if isinstance(tile, dict) and tile.get("kind") == "COOP" and tile.get("animal"):
                    tile["cared_today"] = True
                else:
                    wasted_turns += 1
            elif act == "PASS":
                wasted_turns += 1

        # --- end of day refresh ---
        if (turn + 1) % 24 == 0:
            day += 1
            hires_today = 0
            for y in range(BOARD_SIZE):
                for x in range(BOARD_SIZE):
                    t = tiles[y][x]
                    if not isinstance(t, dict):
                        continue
                    if t.get("kind") == "PLANT":
                        crop = t["crop"]
                        if t["watered_today"]:
                            age = day - t["planted_day"]
                            if age >= 2:
                                t["yield_units"] = min(CAP.get(crop, 4), t["yield_units"] + 1)
                        t["watered_today"] = False
                    elif t.get("kind") == "COOP" and t.get("animal"):
                        if t["fed_today"]:
                            t["yield_units"] = min(4, t["yield_units"] + 1)  # goose max_held=4
                        t["fed_today"] = False
                        t["cared_today"] = False
            # hands disappear at end of day, drop inventory (simplified: discard)
            hands = []
            inventories = [inventories[0]]

    if verbose:
        print(f"\n=== {label} ===")
        print(f"Ran {turn + 1} turns ({day} in-game days).")
        print(f"Final money: {money}  |  shed: {shed}  |  seeds: {seeds}")
        print(f"Quadrants owned: {unlocked_quadrants}")
        print(f"Hands at end: {len(hands)}  |  Wasted-turn actions: {wasted_turns}")
        print(f"Action counts: {action_log}")
        print(f"Errors: {errors if errors else 'none'}")

    return {"money": money, "errors": errors, "wasted": wasted_turns, "actions": action_log}


if __name__ == "__main__":
    run(turns=720, label="Day 7-10 fix, full 30-day season")
