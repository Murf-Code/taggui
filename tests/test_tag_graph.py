"""utils/tag_graph.py against TagBench's src/Explore.tsx. The reference in
explore_reference.json was made by running the TypeScript on the same tag
lists (hsl colors written as hex)."""
import json
from pathlib import Path

from utils.tag_graph import (MAX_GRAPH_TAGS, Edge, cluster, graph_from,
                             group_colors, same_key)

REFERENCE = json.loads((Path(__file__).parent
                        / 'explore_reference.json').read_text())


def test_cluster_matches_explore_tsx():
    model = cluster(REFERENCE['lists'])
    ref = REFERENCE['ref']
    assert ([[n.tag, n.group, n.color] for n in model.nodes]
            == [n[:3] for n in ref['nodes']])
    for node, (_, _, _, x, y) in zip(model.nodes, ref['nodes']):
        assert abs(node.x - x) < 0.2 and abs(node.y - y) < 0.2
    assert (sorted((e.a, e.b) for e in model.edges)
            == sorted(map(tuple, ref['edges'])))
    assert (sorted((e.a, e.b) for e in model.alike)
            == sorted(map(tuple, ref['alike'])))


def test_group_colors_match_explore_tsx():
    assert group_colors(REFERENCE['lists']) == REFERENCE['ref']['colors']


def test_graph_keeps_top_tags():
    _, tags, edges, link_counts = graph_from([['a', 'b'], ['a', 'c'], ['a']])
    assert tags[0] == ('a', 3)
    assert link_counts['a'] == 2
    assert same_key('standing') == same_key('stands')


# The original plain-loop graphFrom, to check the fast one.


def reference_graph_from(tag_lists: list[list[str]]):
    """Tag counts and co-occurrence links of the 90 most common tags."""
    counts: dict[str, list] = {}
    pair: dict[tuple[str, str], int] = {}
    for item_tags in tag_lists:
        unique = list(dict.fromkeys(tag.lower() for tag in item_tags))
        for tag in item_tags:
            key = tag.lower()
            if key in counts:
                counts[key][1] += 1
            else:
                counts[key] = [tag, 1]
        for i in range(len(unique)):
            for j in range(i + 1, len(unique)):
                a, b = unique[i], unique[j]
                key = (a, b) if a < b else (b, a)
                pair[key] = pair.get(key, 0) + 1
    all_tags = sorted(((label, count) for label, count in counts.values()),
                      key=lambda tag: (-tag[1], tag[0].casefold()))
    tags = all_tags[:MAX_GRAPH_TAGS]
    keep = {label.lower() for label, _ in tags}
    edges = sorted((Edge(a, b, w) for (a, b), w in pair.items()
                    if a in keep and b in keep), key=lambda edge: -edge.w)
    link_counts: dict[str, int] = {}
    for edge in edges:
        link_counts[edge.a] = link_counts.get(edge.a, 0) + 1
        link_counts[edge.b] = link_counts.get(edge.b, 0) + 1
    return all_tags, tags, edges, link_counts


def test_fast_graph_from_matches_plain_loop():
    import random
    rng = random.Random(3)
    vocab = [f'Tag{i}' if i % 7 == 0 else f'tag{i}' for i in range(160)]
    for size in (5, 60, 400):
        lists = [[rng.choice(vocab[:rng.randrange(5, 160)])
                  for _ in range(rng.randrange(0, 25))]
                 for _ in range(size)]
        assert graph_from(lists) == reference_graph_from(lists)
    assert graph_from(REFERENCE['lists']) == reference_graph_from(
        REFERENCE['lists'])
