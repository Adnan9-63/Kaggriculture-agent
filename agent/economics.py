"""
Economic model for Kaggriculture.

Computes, for every crop/animal, the rough steady-state $/tile/day and how
much a single day's dump-sell would move its price. This is NOT part of the
submitted agent - it's an offline planning tool to decide what to grow.

Numbers come directly from the competition spec (Object Types + Price
Function tables). Prices are the *base* market price; actual in-game prices
move with inventory, so treat this as a first-pass ranking, not gospel.
"""

# name: (yield_per_tile_per_day, base_price, above_target, seed_or_animal_cost)
CROPS = {
    "WHEAT":      (0.80, 25, 0.20, 10),
    "CARROT":     (0.75, 35, 0.70, 20),
    "TOMATO":     (0.33, 60, 0.60, 50),
    "STRAWBERRY": (0.24, 120, 1.60, 100),
    "MELON":      (0.55, 250, 3.60, 80),
}

ANIMALS = {
    "GOOSE": (1.00, 50, 0.20, 300),
    "COW":   (0.50, 160, 1.60, 400),
    "SHEEP": (0.33, 200, 3.20, 500),
}


def rank():
    rows = []
    for name, (yld, price, above_target, cost) in {**CROPS, **ANIMALS}.items():
        revenue_per_day = yld * price
        # crude "glut risk" score: how aggressively price falls if you oversell.
        # higher above_target = more dangerous to bulk-sell.
        glut_risk = "HIGH" if above_target >= 1.5 else ("MED" if above_target >= 0.6 else "LOW")
        payback_days = cost / revenue_per_day if revenue_per_day else float("inf")
        rows.append((name, revenue_per_day, glut_risk, payback_days, cost))

    rows.sort(key=lambda r: -r[1])
    print(f"{'RESOURCE':<12}{'$/tile/day':<12}{'GLUT RISK':<12}{'PAYBACK(days)':<15}{'START COST'}")
    for name, rev, risk, payback, cost in rows:
        print(f"{name:<12}{rev:<12.1f}{risk:<12}{payback:<15.1f}{cost}")

    print()
    print("Takeaway: LOW/MED glut-risk items (wheat, carrot, tomato, goose) are safe")
    print("to sell in bulk. HIGH glut-risk items (melon, strawberry, cow, sheep) pay")
    print("well per unit but crash hard if oversold in a single day - sell in small")
    print("batches, spread across turns, or time sales around town shop demand.")


if __name__ == "__main__":
    rank()
