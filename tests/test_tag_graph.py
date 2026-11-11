"""utils/tag_graph.py against TagBench's src/Explore.tsx. The reference in
explore_reference.json was made by running the TypeScript on the same tag
lists (hsl colors written as hex)."""
import json
from pathlib import Path

from utils.tag_graph import cluster, graph_from, group_colors, same_key

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
