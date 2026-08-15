"""
Run this on YOUR machine (needs internet + kaggle-environments).
Unlike real_engine_test.py, this doesn't just report the final score - it
samples money, hand count, and market prices over the course of the game
so we can see WHERE things go wrong instead of just THAT they went wrong.

Uses a FIXED SEED so repeated runs are directly comparable - the engine
spawns weeds randomly each episode by default, which was making earlier
single-run comparisons noisy (results varied 4,833 to 8,249 across three
runs of the identical agent). A fixed seed removes that variable.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

from kaggle_environments import make  # noqa: E402
from main import agent  # noqa: E402

SEED = 42  # any fixed value - just needs to be the same across comparison runs


def main():
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": SEED}, debug=True)
    env.run([agent, "starter"])

    steps = env.steps
    print(f"Total steps recorded: {len(steps)} (seed={SEED})")

    sample_every = 24  # once per in-game day
    sample_offset = 2  # hour 2, not hour 0 - hands hired at hour 0 don't
                        # show in the observation until the following hour,
                        # and the previous day's hands vanish at day's end,
                        # so hour 0 always shows hands=0 regardless of
                        # whether hiring is actually working
    print(f"\n{'day':>4} {'money(us)':>10} {'money(opp)':>10} {'hands':>6} "
          f"{'priceW':>7} {'priceC':>7} {'priceE':>7}")

    for day_i, i in enumerate(range(sample_offset, len(steps), sample_every)):
        step = steps[i]
        try:
            s0 = step[0]
            obs = s0.observation if hasattr(s0, "observation") else s0["observation"]
        except Exception as e:
            print(f"[step {i}] couldn't read observation: {e!r}")
            continue

        farms = obs.get("farms", [])
        market = obs.get("market", {})
        if len(farms) < 2:
            continue
        me, opp = farms[0], farms[1]
        prices = market.get("prices", {})
        print(f"{day_i:>4} {me.get('money', '?'):>10} {opp.get('money', '?'):>10} "
              f"{len(me.get('hands', [])):>6} "
              f"{prices.get('WHEAT', '?'):>7} {prices.get('CARROT', '?'):>7} {prices.get('EGG', '?'):>7}")

    final = steps[-1]
    print("\nFinal:")
    for i, s in enumerate(final):
        print(f"Player {i}: reward={s.reward}, status={s.status}")


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
