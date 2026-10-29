#!/usr/bin/env python3
"""Render a run's latest packet as the exact text the relay pastes to the Planner.

Writes packets/relay_NNN.txt and checks that its JSON content equals packets/packet_NNN.json.
Usage: python3 experiments/stage3/render_relay.py RUN_DIR [--first]
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from prsweave.agents.planner import INSTRUCTIONS  # noqa: E402

run_dir = ROOT / sys.argv[1]
latest = sorted((run_dir / "packets").glob("packet_*.json"))[-1]
p = json.loads(latest.read_text())
body = "STATE PACKET:\n{\n" + ",\n".join(f' "{k}": ' + json.dumps(v) for k, v in p.items()) + "\n}"
text = (INSTRUCTIONS + "\n\n" + body) if "--first" in sys.argv else (body + "\n\nReply with only the JSON object.")
assert json.loads(body[body.index("{"):]) == p, "relay text differs from packet"
out = latest.with_name(latest.name.replace("packet_", "relay_").replace(".json", ".txt"))
out.write_text(text)
print(text)
