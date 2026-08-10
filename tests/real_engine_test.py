"""
Run this on YOUR machine (needs internet + `pip install kaggle-environments`).
This uses the real Kaggriculture engine, unlike tests/mock_harness.py.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

from kaggle_environments import make  # noqa: E402
from main import agent  # noqa: E402


def main():
    env = make("kaggriculture", configuration={"episodeSteps": 720}, debug=True)
    env.run([agent, "random"])

    final = env.steps[-1]
    for i, s in enumerate(final):
        print(f"Player {i}: reward={s.reward}, status={s.status}")

    # also test vs the built-in starter agent, which is a stronger baseline
    env2 = make("kaggriculture", configuration={"episodeSteps": 720}, debug=True)
    env2.run([agent, "starter"])
    final2 = env2.steps[-1]
    print("\nvs starter agent:")
    for i, s in enumerate(final2):
        print(f"Player {i}: reward={s.reward}, status={s.status}")


if __name__ == "__main__":
    main()
