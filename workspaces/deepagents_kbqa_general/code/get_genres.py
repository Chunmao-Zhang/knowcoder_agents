import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from collections import defaultdict
import json

# Load the subgraph
subgraph_file = "tools_impl/.subgraph_cache/subgraph_4b7ef250.json"
with open(subgraph_file) as f:
    data = json.load(f)

# Build entity lookup
entities_by_name = {}
entity_name_map = {}

for entity_data in data.get("entities", []):
    en = entity_data.get("_entity_name", "")
    # Create a simple object
    class EntityObj:
        pass
    obj = EntityObj()
    obj._entity_name = en
    obj.starred_actors_r = []
    obj.has_genre = []
    entities_by_name[en] = obj
    entity_name_map[id(obj)] = en

# Populate edges
for edge in data.get("edges", []):
    subj_name = edge.get("subject", "")
    pred = edge.get("predicate", "")
    obj_name = edge.get("object", "")
    
    subj = entities_by_name.get(subj_name)
    obj = entities_by_name.get(obj_name)
    if not subj or not obj:
        continue
    
    if pred == "starred_actors.r":
        subj.starred_actors_r.append(obj)
    elif pred == "has_genre":
        subj.has_genre.append(obj)

def get_name(entity):
    return entity._entity_name

# Actors from The Private War of Major Benson
actors = ['Charlton Heston', 'William Demarest', 'Julie Adams', 'Tim Hovey']

actor_movies_genres = defaultdict(lambda: defaultdict(set))

for actor_name in actors:
    actor = entities_by_name.get(actor_name)
    if not actor:
        print(f"{actor_name}: NOT FOUND")
        continue
    for movie in (actor.starred_actors_r or []):
        movie_name = get_name(movie)
        if movie_name == 'The Private War of Major Benson':
            continue
        for genre in (movie.has_genre or []):
            genre_name = get_name(genre)
            actor_movies_genres[actor_name][movie_name].add(genre_name)

for actor_name in actors:
    if actor_name not in actor_movies_genres or not actor_movies_genres[actor_name]:
        print(f"{actor_name}: (no other movies found)")
        continue
    print(f"\n{actor_name}:")
    for movie_name, genres in sorted(actor_movies_genres[actor_name].items()):
        genres_str = ', '.join(sorted(genres))
        print(f"  - {movie_name}: {genres_str}")