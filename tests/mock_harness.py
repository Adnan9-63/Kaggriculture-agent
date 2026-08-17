"""
Lightweight local test harness for the agent.

IMPORTANT: This is a SIMPLIFIED, hand-rolled approximation of the real
Kaggriculture rules (built from the spec doc), used only to catch Python
errors and sanity-check the agent's decision loop when the real
`kaggle-environments` package isn't installed. It does NOT reproduce the
real market price curve, weed spawning, or town demand.

Before trusting results, run the REAL engine locally (you have internet,
this sandbox doesn't):

    pip install kaggle-environments
    python tests/real_engine_test.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))
from main import agent  # noqa: E402

BOARD_SIZE = 10
STARTING_MONEY = 3000
WHEAT_PRICE = 25  # flat, for sanity-testing only - real price moves


def make_board():
    tiles = [[None for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
    for y in range(BOARD_SIZE):
        for x in range(BOARD_SIZE):
            # Only NW quadrant (0-4, 0-4) starts unlocked.
            if x >= 5 or y >= 5:
                tiles[y][x] = "LOCKED"
    return tiles


def run(turns=200, verbose=True):
    tiles = make_board()
    farmer = [4, 4]
    money = STARTING_MONEY
    shed = {}
    seeds = {}
    day = 0
    errors = []
    actions_taken = {"WATER": 0, "PLANT": 0, "HARVEST": 0, "MOVE": 0, "PASS": 0}
    total_bought = 0
    total_sold_revenue = 0
    total_harvested_units = 0

    for turn in range(turns):
        obs = {
            "player": 0,
            "day": day,
            "hour": turn % 24,
            "farms": [{
                "money": money,
                "tiles": tiles,
                "farmer": farmer,
                "hands": [],
                "unlocked_quadrants": ["NW"],
                "hires_today": 0,
            }],
            "market": {"inventory": {"WHEAT": 10000}, "prices": {"WHEAT": WHEAT_PRICE}},
            "town": {"unlocked_shops": []},
            "private": {
                "shed": shed,
                "seeds": seeds,
                "inventories": [{}],
            },
        }

        try:
            result = agent(obs)
        except Exception as e:
            errors.append((turn, repr(e)))
            if verbose:
                print(f"[turn {turn}] AGENT CRASHED: {e!r}")
            break

        # --- apply market orders (simplified flat pricing) ---
        for order in result.get("market", []):
            if order[0] == "SELL":
                _, item, n = order
                have = shed.get(item, 0)
                n = min(n, have)
                shed[item] = have - n
                money += n * WHEAT_PRICE
                total_sold_revenue += n * WHEAT_PRICE
            elif order[0] == "BUY_SEED":
                _, item, n = order
                cost = n * 10  # wheat seed cost
                if money >= cost:
                    money -= cost
                    seeds[item] = seeds.get(item, 0) + n
                    total_bought += cost
            elif order[0] == "BUY_PRODUCT":
                _, item, n = order
                cost = n * 100  # fertilizer cost
                if money >= cost:
                    money -= cost
                    shed[item] = shed.get(item, 0) + n
                    total_bought += cost
            actions_taken.setdefault(order[0], 0)
            actions_taken[order[0]] += 1

        # --- apply farmer action ---
        fx, fy = farmer
        facts = result.get("farmer", ["PASS"])
        act = facts[0]

        if act in ("NORTH", "SOUTH", "EAST", "WEST"):
            actions_taken["MOVE"] += 1
            if act == "NORTH":
                fy = max(0, fy - 1)
            elif act == "SOUTH":
                fy = min(BOARD_SIZE - 1, fy + 1)
            elif act == "EAST":
                fx = min(BOARD_SIZE - 1, fx + 1)
            elif act == "WEST":
                fx = max(0, fx - 1)
            farmer = [fx, fy]
        elif act == "WATER":
            actions_taken["WATER"] += 1
            t = tiles[fy][fx]
            if isinstance(t, dict):
                t["watered_today"] = True
        elif act == "PLANT":
            actions_taken["PLANT"] += 1
            crop = facts[1]
            if seeds.get(crop, 0) > 0 and tiles[fy][fx] is None:
                seeds[crop] -= 1
                tiles[fy][fx] = {
                    "kind": "PLANT", "crop": crop, "planted_day": day,
                    "watered_today": False, "consecutive_unwatered": 1,
                    "yield_units": 0, "max_lifespan_step": -1,
                    "fertilized_until_day": -1,
                }
        elif act == "HARVEST":
            actions_taken["HARVEST"] += 1
            t = tiles[fy][fx]
            if isinstance(t, dict) and t.get("yield_units", 0) > 0:
                crop = t["crop"]
                shed[crop] = shed.get(crop, 0) + t["yield_units"]
                total_harvested_units += t["yield_units"]
                tiles[fy][fx] = None  # one-time crop, simplified
        elif act == "FERTILIZE":
            actions_taken.setdefault("FERTILIZE", 0)
            actions_taken["FERTILIZE"] += 1
            t = tiles[fy][fx]
            if isinstance(t, dict) and shed.get("FERTILIZER", 0) >= 1:
                shed["FERTILIZER"] -= 1
                t["fertilized_until_day"] = day + 3
        elif act == "DIG":
            actions_taken.setdefault("DIG", 0)
            actions_taken["DIG"] += 1
            t = tiles[fy][fx]
            if isinstance(t, dict) and t.get("kind") == "WEED":
                tiles[fy][fx] = None
        else:
            actions_taken["PASS"] += 1

        # --- end of day refresh every 24 turns ---
        if (turn + 1) % 24 == 0:
            day += 1
            for y in range(BOARD_SIZE):
                for x in range(BOARD_SIZE):
                    t = tiles[y][x]
                    if isinstance(t, dict) and t.get("kind") == "PLANT":
                        if t["watered_today"]:
                            age = day - t["planted_day"]
                            if age >= 2:  # wheat first_yield_day
                                t["yield_units"] = min(4, t["yield_units"] + 1)  # unfertilized wheat cap
                            t["consecutive_unwatered"] = 0
                            t["watered_today"] = False
                        else:
                            t["consecutive_unwatered"] += 1
                            t["watered_today"] = False
                            if t["consecutive_unwatered"] >= 2:
                                tiles[y][x] = {"kind": "WEED"}

    if verbose:
        print(f"\nRan {turn + 1} turns ({day} in-game days).")
        print(f"Final money: {money}  |  shed: {shed}  |  seeds: {seeds}")
        print(f"Action counts: {actions_taken}")
        print(f"Total spent on seed: {total_bought}  |  Total sell revenue: {total_sold_revenue}  |  Units harvested: {total_harvested_units}")
        print(f"Errors: {errors if errors else 'none'}")

    return {"money": money, "errors": errors, "actions": actions_taken}


if __name__ == "__main__":
    result = run(turns=240)  # ~10 in-game days
    if result["errors"]:
        print("\nFAIL: agent raised exceptions during the run.")
        sys.exit(1)
    if result["money"] <= STARTING_MONEY:
        print("\nWARNING: agent did not grow money over the run - check logic.")
    else:
        print("\nOK: agent ran without crashing and grew money.")
