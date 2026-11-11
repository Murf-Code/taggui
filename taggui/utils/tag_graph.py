"""Tag co-occurrence graph, tag groups and the Constellation layout.

A port of TagBench's src/Explore.tsx (graphFrom, grouped, groupColors and
cluster). Everything is computed locally from the tags already on the
images: tags that appear on the same pictures are linked, tags are grouped
by family (e621 categories and implications, then word patterns) and by how
similar their neighbours are, and the groups are laid out with a force
simulation.
"""
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

from utils.tag_categories import TAG_CATEGORY
from utils.tag_implies import TAG_IMPLIES

MAX_GRAPH_TAGS = 90

HUES = ['#ff4d6d', '#ff7a59', '#f0b429', '#d6e15a', '#3ddc97', '#2ee6c7',
        '#3ec6ff', '#5b8cff', '#9b6bff', '#ff7ab6']

SPECIES = ['wolf', 'fox', 'lion', 'feline', 'cat', 'dragon', 'horse', 'avian',
           'bird', 'shark', 'rabbit', 'deer', 'tiger', 'leopard', 'anthro',
           'feral', 'kobold', 'bear', 'otter', 'sergal']

_NEVER = re.compile(r'(?!)')
FAMILIES: list[tuple[str, re.Pattern]] = [
    ('count', re.compile(r'\b(solo|duo|trio|group|multiple|couple|pair)\b',
                         re.I)),
    ('color', re.compile(
        r'\bfur\b|\beyes?\b|sclera|pupil|iris|\bskin\b|marking|\b(black|'
        r'brown|white|grey|gray|tan|pale|pink|red|blue|green|yellow|orange|'
        r'purple|dark|light)\s+body\b', re.I)),
    ('jewelry', re.compile(
        r'jewelry|piercing|bracelet|earring|anklet|necklace|\bring\b', re.I)),
    ('clothing', re.compile(
        r'cloth|shirt|dress|\bwear\b|loincloth|glove|topless|nude|\bpant|'
        r'skirt|jacket|collar|outfit|clothed', re.I)),
    ('species', re.compile(rf'\b({"|".join(SPECIES)})\b', re.I)),
    ('pose', re.compile(
        r'look|smile|\bmouth\b|standing|sitting|holding|blush|gaze', re.I)),
    ('gender', re.compile(r'\bmale\b|\bfemale\b|gender|\bboy\b|\bgirl\b',
                          re.I)),
    ('place', re.compile(
        r'outdoor|indoor|\bnight\b|background|\bsky\b|outside|\blight\b',
        re.I)),
    ('object', re.compile(
        r'\b(book|bottle|cup|lamp|plant|container|fire|candle|box|bag|phone|'
        r'camera|sword|spear|weapon|food|drink|chair|table|bed)\b', re.I)),
    ('framing', re.compile(
        r'\bfull body\b|\bupper body\b|\blower body\b|\bbust\b|\bportrait\b|'
        r'\bclose[- ]?up\b|\bcowboy shot\b', re.I)),
    ('body', re.compile(
        r'paw|claw|tail|whisker|fang|\bear\b|finger|toe|\bfeet\b|\bfoot\b|'
        r'nipple|breast|pectoral|\babs\b|muscular|tuft|\bnose\b|muzzle|horn|'
        r'wing|thigh|biped|\bbody\b|digitigrade|\bhair\b|navel|collarbone|'
        r'eyebrow', re.I)),
    ('character', _NEVER),
    ('copyright', _NEVER),
    ('meta', _NEVER),
    ('lore', _NEVER),
]
FAMILY_IDS = [family_id for family_id, _ in FAMILIES]


@dataclass
class Edge:
    a: str
    b: str
    w: float


@dataclass
class Node:
    tag: str
    count: int
    links: int
    x: float
    y: float
    color: str
    group: int


@dataclass
class ClusterModel:
    nodes: list[Node] = field(default_factory=list)
    # Strongest links inside a group (drawn as thin lines).
    edges: list[Edge] = field(default_factory=list)
    # Every link between two shown tags (pictures shared).
    pairs: list[Edge] = field(default_factory=list)
    # Tags that are the same word (dashed lines).
    alike: list[Edge] = field(default_factory=list)


def link_radius(links: int, min_links: int, max_links: int) -> float:
    span = max_links - min_links
    t = 1 if span <= 0 else (links - min_links) / span
    return 4 + t * 22


def same_key(label: str) -> str:
    word = re.sub(r'[\s_]', '', label.lower())
    if word.endswith('ing') and len(word) > 6:
        return word[:-3]
    if word.endswith('ed') and len(word) > 5:
        return word[:-2]
    if word.endswith('es') and len(word) > 4:
        return word[:-2]
    if word.endswith('s') and len(word) > 3:
        return word[:-1]
    return word


def base_family(label: str) -> int | None:
    word = label.strip().lower().replace(' ', '_')
    spaced = word.replace('_', ' ')
    category = TAG_CATEGORY.get(word)
    if category == 5:
        return FAMILY_IDS.index('species')
    if category == 4:
        return FAMILY_IDS.index('character')
    if category == 3:
        return FAMILY_IDS.index('copyright')
    if category == 7:
        return FAMILY_IDS.index('meta')
    if category == 8:
        return FAMILY_IDS.index('lore')
    if ' ' not in spaced and any(spaced != name and name in spaced
                                 for name in SPECIES):
        return FAMILY_IDS.index('character')
    for index, (_, test) in enumerate(FAMILIES):
        if test.search(word) or test.search(spaced):
            return index
    return None


@lru_cache(maxsize=20000)
def family_of(label: str) -> int | None:
    seen = set()

    def walk(name: str, depth: int) -> int | None:
        key = name.strip().lower().replace(' ', '_')
        if not key or key in seen or depth > 4:
            return None
        seen.add(key)
        direct = base_family(key)
        if direct is not None:
            return direct
        for parent in TAG_IMPLIES.get(key, []):
            found = walk(parent, depth + 1)
            if found is not None:
                return found
        return None

    return walk(label, 0)


def hue_for(group_id: int) -> str:
    if group_id < len(HUES):
        return HUES[group_id]
    hue = round((group_id * 137.508) % 360)
    # hsl(h 72% 62%) as hex.
    from colorsys import hls_to_rgb
    r, g, b = hls_to_rgb(hue / 360, 0.62, 0.72)
    return '#{:02x}{:02x}{:02x}'.format(round(r * 255), round(g * 255),
                                        round(b * 255))


def group_by_similarity(tags: list[tuple[str, int]],
                        edges: list[Edge]) -> dict[str, int]:
    """Complete-linkage clusters of tags whose neighbours are alike, cut at
    whichever height separates the groups best."""
    n = len(tags)
    if n == 0:
        return {}
    at = {label.lower(): index for index, (label, _) in enumerate(tags)}
    shared = np.zeros((n, n))
    for edge in edges:
        i = at.get(edge.a.lower())
        j = at.get(edge.b.lower())
        if i is None or j is None:
            continue
        shared[i, j] = edge.w
        shared[j, i] = edge.w
    counts = np.array([count or 1 for _, count in tags], dtype=float)
    raw_counts = np.array([count for _, count in tags], dtype=float)
    pictures = max(max(raw_counts), 1)
    rare = np.log((n + 1) / (counts + 1))
    usable = raw_counts <= pictures * 0.5
    weights = (shared / counts[:, None]) * (rare * usable)[None, :]
    # Terms k == i and k == j drop out: shared[i, i] is 0, and the k == j
    # term of the norms is removed below.
    dot = weights @ weights.T
    squares = (weights ** 2).sum(axis=1)
    left = np.maximum(squares[:, None] - weights ** 2, 0)
    right = left.T
    norm = left * right
    with np.errstate(divide='ignore', invalid='ignore'):
        cosine = np.where((left > 1e-15) & (right > 1e-15),
                          dot / np.sqrt(np.where(norm > 0, norm, 1)), 0)
    base = 1 - cosine
    np.fill_diagonal(base, 0)

    def cut_at(limit: float) -> list[int]:
        dist = base.copy()
        rep = list(range(n))
        alive = np.ones(n, dtype=bool)
        upper = np.triu(np.ones((n, n), dtype=bool), 1)
        while alive.sum() > 1:
            mask = upper & alive[:, None] & alive[None, :]
            candidates = np.where(mask, dist, np.inf)
            flat = int(np.argmin(candidates))
            best = candidates.flat[flat]
            if not np.isfinite(best) or best > limit:
                break
            keep, drop = divmod(flat, n)
            others = alive.copy()
            others[keep] = others[drop] = False
            merged = np.maximum(dist[keep], dist[drop])
            dist[keep, others] = merged[others]
            dist[others, keep] = merged[others]
            alive[drop] = False
            rep = [keep if r == drop else r for r in rep]
        return rep

    def score(rep: list[int]) -> float:
        groups: dict[int, list[int]] = {}
        for i in range(n):
            groups.setdefault(rep[i], []).append(i)
        if len(groups) < 2:
            return -1
        total = 0.0
        used = 0
        for i in range(n):
            mine = groups[rep[i]]
            if len(mine) < 2:
                continue
            near = sum(base[i, j] for j in mine if j != i) / (len(mine) - 1)
            far = math.inf
            for group_id, members in groups.items():
                if group_id == rep[i]:
                    continue
                mean = sum(base[i, j] for j in members) / len(members)
                far = min(far, mean)
            total += (far - near) / max(near, far, 1e-6)
            used += 1
        return total / used if used else -1

    best_rep = cut_at(0.45)
    best_score = score(best_rep)
    for limit in (0.25, 0.35, 0.55, 0.7):
        rep = cut_at(limit)
        value = score(rep)
        if value > best_score:
            best_score = value
            best_rep = rep
    ids: dict[int, int] = {}
    group: dict[str, int] = {}
    for i, (label, _) in enumerate(tags):
        root = best_rep[i]
        ids.setdefault(root, len(ids))
        group[label] = ids[root]
    return group


def grouped(tags: list[tuple[str, int]], edges: list[Edge]
            ) -> tuple[dict[str, int], dict[str, int]]:
    keys = [label for label, _ in tags]
    learned = group_by_similarity(tags, edges)
    group: dict[str, int] = {}
    leftover: dict[int, int] = {}
    next_id = len(FAMILIES)
    for tag in keys:
        family = family_of(tag)
        if family is not None:
            group[tag] = family
            continue
        learned_id = learned.get(tag, next_id)
        if learned_id not in leftover:
            leftover[learned_id] = next_id
            next_id += 1
        group[tag] = leftover[learned_id]
    count_of = dict(tags)
    alike_buckets: dict[str, list[str]] = {}
    for tag in keys:
        key = same_key(tag)
        if len(key) < 4:
            continue
        alike_buckets.setdefault(key, []).append(tag)
    alike_id: dict[str, int] = {}
    alike_seq = 1
    for members in alike_buckets.values():
        if len(members) < 2:
            continue
        ranked = sorted(members, key=lambda tag: -count_of.get(tag, 0))
        leader = next((tag for tag in ranked if family_of(tag) is not None),
                      ranked[0])
        chosen = group[leader]
        for tag in members:
            group[tag] = chosen
            alike_id[tag] = alike_seq
        alike_seq += 1
    remap: dict[int, int] = {}
    for group_id in group.values():
        remap.setdefault(group_id, len(remap))
    return {tag: remap[group_id] for tag, group_id in group.items()}, alike_id


def graph_from(tag_lists: list[list[str]]):
    """Tag counts and co-occurrence links of the 90 most common tags.

    Same result as counting every pair of tags on every image, but only
    pairs among the top tags are counted, with numpy, so it stays quick on
    tens of thousands of images."""
    counts: dict[str, list] = {}
    lowered_lists = []
    for item_tags in tag_lists:
        lowered = [tag.lower() for tag in item_tags]
        lowered_lists.append(lowered)
        for tag, key in zip(item_tags, lowered):
            entry = counts.get(key)
            if entry is None:
                counts[key] = [tag, 1]
            else:
                entry[1] += 1
    all_tags = sorted(((label, count) for label, count in counts.values()),
                      key=lambda tag: (-tag[1], tag[0].casefold()))
    tags = all_tags[:MAX_GRAPH_TAGS]
    keep = [label.lower() for label, _ in tags]
    column_of = {key: column for column, key in enumerate(keep)}
    width = len(keep)
    # For each image, where each kept tag sits among its unique tags
    # (-1 when absent). The order decides ties, as in the plain loop.
    rows, columns, places = [], [], []
    for row, lowered in enumerate(lowered_lists):
        for place, key in enumerate(dict.fromkeys(lowered)):
            column = column_of.get(key)
            if column is not None:
                rows.append(row)
                columns.append(column)
                places.append(place)
    edges: list[Edge] = []
    if width > 1 and rows:
        position = np.full((len(tag_lists), width), -1, np.int64)
        position[rows, columns] = places
        present = position >= 0
        weights = present.T.astype(np.int64) @ present.astype(np.int64)
        found = []
        for i in range(width - 1):
            both = present[:, i:i + 1] & present[:, i + 1:]
            firsts = np.argmax(both, axis=0)
            for offset in np.nonzero(weights[i, i + 1:])[0].tolist():
                j = i + 1 + offset
                first = int(firsts[offset])
                place_i = int(position[first, i])
                place_j = int(position[first, j])
                a, b = keep[i], keep[j]
                key = (a, b) if a < b else (b, a)
                found.append(((first, min(place_i, place_j),
                               max(place_i, place_j)), key,
                              int(weights[i, j])))
        # First seen order, then the heaviest first (a stable sort).
        found.sort(key=lambda item: item[0])
        edges = sorted((Edge(a, b, w) for _, (a, b), w in found),
                       key=lambda edge: -edge.w)
    link_counts: dict[str, int] = {}
    for edge in edges:
        link_counts[edge.a] = link_counts.get(edge.a, 0) + 1
        link_counts[edge.b] = link_counts.get(edge.b, 0) + 1
    return all_tags, tags, edges, link_counts


def group_colors(tag_lists: list[list[str]],
                 color_for=lambda tag: None) -> dict[str, str]:
    """A color for every tag: its own category color, else its group's."""
    all_tags, tags, edges, _ = graph_from(tag_lists)
    group, _ = grouped(tags, edges)
    colors: dict[str, str] = {}
    by_family: dict[int, str] = {}
    by_stem: dict[str, str] = {}
    for label, _ in tags:
        hue = hue_for(group.get(label, 0))
        colors[label.lower()] = color_for(label) or hue
        family = family_of(label)
        if family is not None and family not in by_family:
            by_family[family] = hue
        stem = same_key(label)
        if len(stem) >= 4 and stem not in by_stem:
            by_stem[stem] = hue
    for label, _ in all_tags:
        key = label.lower()
        if key in colors:
            continue
        painted = color_for(label)
        if painted:
            colors[key] = painted
            continue
        stem = same_key(label)
        family = family_of(label)
        hue = (len(stem) >= 4 and by_stem.get(stem)) or (
            by_family.get(family, hue_for(family)) if family is not None
            else '')
        if hue:
            colors[key] = hue
    return colors


def cluster(tag_lists: list[list[str]],
            color_for=lambda tag: None) -> ClusterModel:
    """Lay out the Constellation: groups around a ring, pulled together by
    their strongest links and pushed apart so circles do not overlap."""
    _, tags, edges, link_counts = graph_from(tag_lists)
    if not tags:
        return ClusterModel()
    keys = [label for label, _ in tags]
    known = {tag.lower(): tag for tag in keys}
    links: list[Edge] = []
    for edge in edges:
        a = known.get(edge.a.lower())
        b = known.get(edge.b.lower())
        if not a or not b or a == b:
            continue
        links.append(Edge(a, b, edge.w))
    group, _ = grouped(tags, edges)
    count_of = dict(tags)
    bodies = []
    for label, count in tags:
        group_id = group[label]
        bodies.append({'tag': label, 'count': count, 'group': group_id,
                       'links': link_counts.get(label.lower(), 0),
                       'color': color_for(label) or hue_for(group_id),
                       'x': 500.0, 'y': 360.0})
    at = {body['tag']: index for index, body in enumerate(bodies)}
    mass = np.array([1 + math.sqrt(body['links']) for body in bodies])
    group_ids = list(dict.fromkeys(body['group'] for body in bodies))
    group_weight = {group_id: sum(body['links'] for body in bodies
                                  if body['group'] == group_id)
                    for group_id in group_ids}
    ordered = sorted(group_ids, key=lambda group_id: -group_weight[group_id])
    for index, group_id in enumerate(ordered):
        turn = index / max(len(ordered), 1) * math.pi * 2 - math.pi / 2
        members = sorted((body for body in bodies
                          if body['group'] == group_id),
                         key=lambda body: (-body['links'], -body['count']))
        for rank, body in enumerate(members):
            angle = rank * 2.399
            local = 0 if rank == 0 else 18 + math.sqrt(rank) * 12
            body['x'] = math.cos(turn) * 210 + math.cos(angle) * local
            body['y'] = math.sin(turn) * 170 + math.sin(angle) * local
    shown: list[Edge] = []
    attract: list[tuple[int, int, float]] = []
    seen = set()
    picked_edges: list[tuple[Edge, bool]] = []
    for tag in keys:
        mine = [edge for edge in links if tag in (edge.a, edge.b)]

        def other(edge):
            return edge.b if edge.a == tag else edge.a

        inside = sorted((edge for edge in mine
                         if group.get(other(edge)) == group.get(tag)),
                        key=lambda edge: -edge.w)[:3]
        outside = sorted((edge for edge in mine
                          if group.get(other(edge)) != group.get(tag)),
                         key=lambda edge: -edge.w)[:1]
        picked_edges += [(edge, True) for edge in inside]
        picked_edges += [(edge, False) for edge in outside]
    max_edge = max([edge.w for edge, _ in picked_edges] + [1])
    for edge, is_inside in picked_edges:
        key = (edge.a, edge.b) if edge.a < edge.b else (edge.b, edge.a)
        if key in seen:
            continue
        seen.add(key)
        i, j = at.get(edge.a), at.get(edge.b)
        if i is None or j is None:
            continue
        attract.append((i, j, (0.45 + 0.55 * (edge.w / max_edge))
                        * (1 if is_inside else 0.08)))
        if is_inside:
            shown.append(edge)
    x = np.array([body['x'] for body in bodies])
    y = np.array([body['y'] for body in bodies])
    if attract:
        attract_i = np.array([edge[0] for edge in attract])
        attract_j = np.array([edge[1] for edge in attract])
        attract_w = np.array([edge[2] for edge in attract])
    scaling, attract_k, gravity = 2, 3, 0.012
    mass_product = mass[:, None] * mass[None, :]
    for step in range(220):
        dx = x[:, None] - x[None, :]
        dy = y[:, None] - y[None, :]
        dist = np.hypot(dx, dy)
        dist[dist == 0] = 0.01
        factor = scaling * mass_product / dist / dist
        np.fill_diagonal(factor, 0)
        fx = (dx * factor).sum(axis=1)
        fy = (dy * factor).sum(axis=1)
        if attract:
            adx = x[attract_i] - x[attract_j]
            ady = y[attract_i] - y[attract_j]
            adist = np.hypot(adx, ady)
            adist[adist == 0] = 0.01
            afactor = -attract_k * attract_w * np.log(1 + adist) / adist
            np.add.at(fx, attract_i, adx * afactor)
            np.add.at(fy, attract_i, ady * afactor)
            np.add.at(fx, attract_j, -adx * afactor)
            np.add.at(fy, attract_j, -ady * afactor)
        pull = gravity * mass
        fx -= x * pull
        fy -= y * pull
        max_force = max(1.0, float(np.hypot(fx, fy).max()))
        max_step = 8 * 0.99 ** step + 0.6
        step_scale = min(0.35, max_step / max_force)
        x += fx * step_scale
        y += fy * step_scale
    link_values = [body['links'] for body in bodies]
    min_links, max_links = min(link_values), max(link_values + [1])
    radii = [link_radius(links, min_links, max_links) for links in link_values]
    count = len(bodies)
    for _ in range(28):
        for i in range(count):
            for j in range(i + 1, count):
                dx = x[i] - x[j]
                dy = y[i] - y[j]
                dist = max(1.0, math.hypot(dx, dy))
                min_dist = radii[i] + radii[j] + 14
                if dist >= min_dist:
                    continue
                dx /= dist
                dy /= dist
                push = (min_dist - dist) / 2
                x[i] += dx * push
                y[i] += dy * push
                x[j] -= dx * push
                y[j] -= dy * push
    x += 500
    y += 360
    alike_buckets: dict[str, list[str]] = {}
    for tag in keys:
        key = same_key(tag)
        if len(key) >= 4:
            alike_buckets.setdefault(key, []).append(tag)
    alike: list[Edge] = []
    for members in alike_buckets.values():
        if len(members) < 2:
            continue
        leader = sorted(members, key=lambda tag: -count_of.get(tag, 0))[0]
        alike += [Edge(leader, tag, 0) for tag in members if tag != leader]
    nodes = [Node(body['tag'], body['count'], body['links'], float(x[i]),
                  float(y[i]), body['color'], body['group'])
             for i, body in enumerate(bodies)]
    return ClusterModel(nodes, shown, links, alike)
