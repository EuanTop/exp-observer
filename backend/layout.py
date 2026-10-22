"""Deterministic semantic placement with immutable manual coordinates.

Containment defines visual scopes only for explicit containers. Semantic cycles
use stable node order to identify feedback arcs; chronology-only edges do not affect ranking. Coordinates are
absolute, matching the canvas model.
"""
from collections import defaultdict
import heapq

WIDTH, HEIGHT = 368, 230
GAP = 52
STEP_X, STEP_Y = WIDTH + GAP, HEIGHT + GAP


def is_container(node):
    return node.get('isContainer', node.get('kind') == 'group') is True


def semantic_edges(edges):
    return [edge for edge in edges if str(edge.get('relation', '')).strip().lower() != 'recorded_after']


def ranks(node_ids, pairs):
    """Longest-path ranks after deterministic SCC feedback removal, without recursion."""
    order = {key: index for index, key in enumerate(node_ids)}
    forward, backward = {key: set() for key in node_ids}, {key: set() for key in node_ids}
    for source, target in pairs:
        if source in forward and target in forward and source != target:
            forward[source].add(target)
            backward[target].add(source)
    seen, finish = set(), []
    for start in node_ids:
        if start in seen:
            continue
        seen.add(start)
        stack = [(start, iter(sorted(forward[start], key=order.get)))]
        while stack:
            current, neighbors = stack[-1]
            child = next(neighbors, None)
            if child is None:
                finish.append(current)
                stack.pop()
            elif child not in seen:
                seen.add(child)
                stack.append((child, iter(sorted(forward[child], key=order.get))))
    component, groups = {}, []
    for start in reversed(finish):
        if start in component:
            continue
        group = len(groups)
        groups.append([])
        component[start] = group
        stack = [start]
        while stack:
            current = stack.pop()
            groups[group].append(current)
            for parent in sorted(backward[current], key=order.get, reverse=True):
                if parent not in component:
                    component[parent] = group
                    stack.append(parent)
    outgoing = {key: set() for key in node_ids}
    incoming = {key: set() for key in node_ids}
    indegree = {key: 0 for key in node_ids}
    levels = {key: 0 for key in node_ids}
    for source in node_ids:
        for target in forward[source]:
            # Inside a cycle, retain forward relationships and draw backward
            # arcs as feedback. Adding a revisit need not flatten an old chain.
            if component[source] != component[target] or order[source] < order[target]:
                outgoing[source].add(target)
                incoming[target].add(source)
                indegree[target] += 1
    ready = [(order[key], key) for key in node_ids if not indegree[key]]
    heapq.heapify(ready)
    while ready:
        _, current = heapq.heappop(ready)
        for child in sorted(outgoing[current], key=order.get):
            levels[child] = max(levels[child], levels[current] + 1)
            indegree[child] -= 1
            if not indegree[child]:
                heapq.heappush(ready, (order[child], child))
    return levels, incoming


def legacy_column_candidate(nodes, edges):
    """Recognize only the entire exact old root grid, never approximate positions."""
    if len(nodes) < 3 or any('positionSource' in node or node.get('parentId') is not None or is_container(node) for node in nodes):
        return False
    if any(node.get('position') != {'x': 40, 'y': 40 + STEP_Y * index} for index, node in enumerate(nodes)):
        return False
    pairs = [(edge['source'], edge['target']) for edge in semantic_edges(edges)]
    levels, _ = ranks([node['id'] for node in nodes], pairs)
    children = defaultdict(set)
    for source, target in pairs:
        if source in levels and target in levels and levels[target] > levels[source]:
            children[source].add(target)
    return any(len({target for target in targets if levels[target] == rank}) >= 2
               for source, targets in children.items() for rank in {levels[target] for target in targets})


def nearest_slot(desired, minimum, y, width, height, occupied):
    """Find the nearest free horizontal interval; there is no finite search cap."""
    intervals = sorted((ox - width - GAP, ox + ow + GAP) for ox, oy, ow, oh in occupied
                       if not (y + height + GAP <= oy or oy + oh + GAP <= y))
    merged = []
    for left, right in intervals:
        if merged and left < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], right))
        else:
            merged.append((left, right))
    desired = max(minimum, desired)
    for left, right in merged:
        if left < desired < right:
            return min((point for point in (left, right) if point >= minimum),
                       key=lambda point: (abs(point - desired), point))
    return desired


def layout_nodes(nodes, edges, new_ids=()):
    """Place automatic nodes; reserve manual pins and retain valid existing slots.

    Returns IDs whose positions changed. Existing manual/manual overlaps cannot
    be repaired without moving a pin; automatic nodes avoid all reserved bounds.
    """
    if not nodes:
        return set()
    by_id = {node['id']: node for node in nodes}
    order = {node['id']: index for index, node in enumerate(nodes)}
    new_ids = set(new_ids)
    original = {node['id']: dict(node['position']) for node in nodes}
    children = defaultdict(list)
    for node in nodes:
        children[node.get('parentId')].append(node['id'])
    scope_of = {}
    for node in nodes:
        parent = by_id.get(node.get('parentId'))
        while parent and not is_container(parent):
            parent = by_id.get(parent.get('parentId'))
        scope_of[node['id']] = parent['id'] if parent else None
    scopes = defaultdict(list)
    for node in nodes:
        scopes[scope_of[node['id']]].append(node['id'])
    pinned = {node['id'] for node in nodes if node.get('positionSource') != 'auto'}
    # A manual descendant anchors its container as well; moving the frame must
    # never silently change that descendant's absolute coordinates or bounds.
    for node_id in list(pinned):
        parent = by_id.get(by_id[node_id].get('parentId'))
        while parent:
            if is_container(parent):
                pinned.add(parent['id'])
            parent = by_id.get(parent.get('parentId'))

    def rectangle(node_id):
        boxes, pending = {}, [(node_id, False)]
        while pending:
            current, ready = pending.pop()
            node = by_id[current]
            x, y = node['position']['x'], node['position']['y']
            nested = scopes[current] if is_container(node) and not node.get('collapsed', False) else []
            if nested and not ready:
                pending.append((current, True))
                pending.extend((child, False) for child in nested)
                continue
            width, height = WIDTH, HEIGHT
            if nested:
                width = max(330, *(boxes[child][0] + boxes[child][2] - x + 28 for child in nested))
                height = max(HEIGHT, *(boxes[child][1] + boxes[child][3] - y + 28 for child in nested))
            boxes[current] = (x, y, width, height)
        return boxes[node_id]

    def move(node_id, x, y):
        node = by_id[node_id]
        dx, dy = x - node['position']['x'], y - node['position']['y']
        node['position'] = {'x': x, 'y': y}
        if is_container(node) and (dx or dy):
            pending = list(children[node_id])
            while pending:
                child = pending.pop()
                pos = by_id[child]['position']
                by_id[child]['position'] = {'x': pos['x'] + dx, 'y': pos['y'] + dy}
                pending.extend(children[child])

    def representative(node_id, scope):
        while node_id in by_id:
            if scope_of[node_id] == scope:
                return node_id
            node_id = scope_of[node_id]
        return None

    def free(x, y, width, height, occupied):
        return all(x + width + GAP <= ox or ox + ow + GAP <= x or
                   y + height + GAP <= oy or oy + oh + GAP <= y
                   for ox, oy, ow, oh in occupied)

    # Process inner scopes first so outer collision checks include descendants.
    def place_scope(scope):
        members = scopes[scope]
        if not members:
            return
        frame = by_id.get(scope)
        origin_x = frame['position']['x'] + 30 if frame else 40
        origin_y = frame['position']['y'] + 100 if frame else 40
        pairs = set()
        for edge in semantic_edges(edges):
            source, target = representative(edge['source'], scope), representative(edge['target'], scope)
            if source and target and source != target:
                pairs.add((source, target))
        # Ordinary parents organize research but remain cards in the same scope.
        for node_id in members:
            parent = by_id[node_id].get('parentId')
            if parent in by_id and scope_of[parent] == scope and parent != node_id:
                pairs.add((parent, node_id))
        levels, predecessors = ranks(members, pairs)
        occupied = [rectangle(node_id) for node_id in members if node_id in pinned]
        for node_id in sorted(members, key=lambda key: (levels[key], order[key])):
            if node_id in pinned:
                continue
            node = by_id[node_id]
            _, _, width, height = rectangle(node_id)
            parents = sorted((parent for parent in predecessors[node_id] if levels[parent] < levels[node_id]), key=order.get)
            y = max([origin_y + levels[node_id] * STEP_Y] + [rectangle(parent)[1] + rectangle(parent)[3] + GAP for parent in parents])
            x = max(origin_x, sum(by_id[parent]['position']['x'] + rectangle(parent)[2] / 2 for parent in parents) / len(parents) - width / 2) if parents else origin_x
            old = node['position']
            if node_id not in new_ids and old['x'] >= origin_x and abs(old['y'] - y) <= 1 and free(old['x'], y, width, height, occupied):
                x = old['x']
            else:
                x = nearest_slot(x, origin_x, y, width, height, occupied)
            move(node_id, x, y)
            occupied.append(rectangle(node_id))
    pending = [(None, False)]
    while pending:
        scope, ready = pending.pop()
        if ready:
            place_scope(scope)
        else:
            pending.append((scope, True))
            pending.extend((key, False) for key in scopes[scope] if is_container(by_id[key]))
    return {node['id'] for node in nodes if node['position'] != original[node['id']]}
