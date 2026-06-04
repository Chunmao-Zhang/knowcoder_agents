import json

# Read the subgraph cache
with open("tools_impl/.subgraph_cache/subgraph_2d05daf0.json") as f:
    data = json.load(f)

# Collect all movies from starred_actors.r relationships
movies = set()
for entity_name, entity_data in data.get("entities", {}).items():
    if entity_name == "The Private War of Major Benson":
        continue
    # Check incoming starred_actors (starred_actors.r)
    incoming = entity_data.get("incoming", {})
    for rel_name, rel_targets in incoming.items():
        if "starred_actors" in rel_name:
            for target in rel_targets:
                if target != "The Private War of Major Benson":
                    movies.add(target)

sorted_movies = sorted(movies)
print(f"Total unique movies: {len(sorted_movies)}")
for m in sorted_movies:
    print(m)