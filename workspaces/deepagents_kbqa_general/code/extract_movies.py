import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
# Read the subgraph cache
with open(ROOT / "data/deepagents_kbqa_general/runtime/tools_impl/.subgraph_cache/subgraph_2d05daf0.json") as f:
    data = json.load(f)

# Extract all unique movies (objects of starred_actors.r triples)
movies = set()
for s, p, o in data["triplets"]:
    if p == "starred_actors.r":
        movies.add(o)

# Remove the seed movie
seed = "The Private War of Major Benson"
movies.discard(seed)

# Sort and print
movies_sorted = sorted(movies)
print(f"Total unique movies (excluding seed): {len(movies_sorted)}")
for m in movies_sorted:
    print(m)