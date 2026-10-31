import json
import sys

def main(filepath):
    print(f"\nAnalyzing {filepath}...")
    with open(filepath, 'r') as f:
        data = json.load(f)
    
    team_names = data.get("info", {}).get("TeamNames", [])
    our_index = 0
    if "Md. Adnan" in team_names:
        our_index = team_names.index("Md. Adnan")
    else:
        print("Warning: Md. Adnan not found in TeamNames, defaulting to 0.")
    
    steps = data.get("steps", [])
    
    print(f"{'Day':>4} {'Our Money':>10} {'Opp Money':>10} {'WHEAT':>7} {'MELON':>7} {'STRAW':>7} {'FERT':>7} {'Our Quads':>10}")
    
    for i, step in enumerate(steps):
        if i % 24 != 23 and i != len(steps) - 1:
            continue
            
        day = i // 24
        
        obs = step[0].get("observation", {})
        farms = obs.get("farms", [])
        
        if len(farms) < 2:
            continue
            
        us = farms[our_index]
        opp = farms[1 - our_index]
        
        our_money = us.get("money", 0)
        opp_money = opp.get("money", 0)
        
        market = obs.get("market", {})
        prices = market.get("prices", {})
        
        wheat = prices.get("WHEAT", 0)
        carrot = prices.get("MELON", 0)
        straw = prices.get("STRAWBERRY", 0)
        fert = prices.get("FERTILIZER", 0)
        
        our_quads = len(us.get("unlocked_quadrants", []))
        
        print(f"{day:>4} {our_money:>10.1f} {opp_money:>10.1f} {wheat:>7} {carrot:>7} {straw:>7} {fert:>7} {our_quads:>10}")

if __name__ == "__main__":
    main(sys.argv[1])
