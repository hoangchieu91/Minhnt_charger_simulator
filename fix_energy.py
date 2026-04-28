import json
import random

STATE_FILE = "simulator_state.json"
try:
    with open(STATE_FILE, 'r') as f:
        state = json.load(f)
except:
    state = {"slaves": {}}

for slave_id, s_data in state.get("slaves", {}).items():
    s_data["energy"] = random.randint(100000, 200000)

with open(STATE_FILE, 'w') as f:
    json.dump(state, f, indent=2)

print("Restored energy to simulator_state.json")
