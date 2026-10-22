import copy
import tempfile
import unittest
from pathlib import Path

from backend.layout import GAP, HEIGHT, WIDTH, is_container, layout_nodes, legacy_column_candidate
from backend.store import Store, StoreError


def node(key, **patch):
    return {'id': key, 'title': key, 'kind': 'question', 'parentId': None, 'position': {'x': 0, 'y': 0},
            'positionSource': 'auto', 'collapsed': False, **patch}


def edge(source, target, relation='branches'):
    return {'id': f'{source}-{target}-{relation}', 'source': source, 'target': target, 'relation': relation}


def visual_scope(nodes, current):
    by_id = {n['id']: n for n in nodes}
    parent = by_id.get(current.get('parentId'))
    while parent and not is_container(parent):
        parent = by_id.get(parent.get('parentId'))
    return parent['id'] if parent else None


def bounds(nodes, current):
    x, y = current['position']['x'], current['position']['y']
    children = [n for n in nodes if visual_scope(nodes, n) == current['id']]
    if is_container(current) and not current.get('collapsed') and children:
        boxes = [bounds(nodes, child) for child in children]
        return x, y, max(330, *(cx + cw - x + 28 for cx, cy, cw, ch in boxes)), max(HEIGHT, *(cy + ch - y + 28 for cx, cy, cw, ch in boxes))
    return x, y, WIDTH, HEIGHT


class LayoutAlgorithmTests(unittest.TestCase):
    def assertNoOverlap(self, nodes):
        for index, first in enumerate(nodes):
            for second in nodes[index + 1:]:
                if visual_scope(nodes, first) != visual_scope(nodes, second):
                    continue
                x, y, w, h = bounds(nodes, first)
                ox, oy, ow, oh = bounds(nodes, second)
                self.assertTrue(x + w <= ox or ox + ow <= x or y + h <= oy or oy + oh <= y,
                                f'{first["id"]} overlaps {second["id"]}')

    def test_diamond_split_merge_and_deterministic_cycle(self):
        nodes = [node(key) for key in ('goal', 'left', 'right', 'merge')]
        edges = [edge('goal', 'left'), edge('goal', 'right'), edge('left', 'merge'), edge('right', 'merge')]
        layout_nodes(nodes, edges, {n['id'] for n in nodes})
        goal, left, right, merge = [n['position'] for n in nodes]
        self.assertEqual(left['y'], right['y'])
        self.assertGreaterEqual(abs(left['x'] - right['x']), WIDTH + GAP)
        self.assertLess(goal['y'], left['y'])
        self.assertLess(left['y'], merge['y'])
        self.assertGreaterEqual(merge['x'], min(left['x'], right['x']))
        self.assertLessEqual(merge['x'], max(left['x'], right['x']))
        self.assertNoOverlap(nodes)
        cycle = [edge('a', 'b'), edge('b', 'c', 'revisits'), edge('c', 'a', 'revisits'), edge('c', 'd')]
        first = [node(key) for key in 'abcd']
        second = copy.deepcopy(first)
        layout_nodes(first, cycle, set('abcd'))
        layout_nodes(second, list(reversed(cycle)), set('abcd'))
        self.assertEqual(first, second)
        self.assertLess(first[0]['position']['y'], first[1]['position']['y'])
        self.assertLess(first[1]['position']['y'], first[2]['position']['y'])
        self.assertLess(first[0]['position']['y'], first[3]['position']['y'])
        self.assertNoOverlap(first)

    def test_recorded_after_does_not_turn_siblings_into_a_chain(self):
        nodes = [node(key) for key in 'abc']
        layout_nodes(nodes, [edge('a', 'b'), edge('a', 'c'), edge('b', 'c', 'recorded_after')], set('abc'))
        self.assertEqual(nodes[1]['position']['y'], nodes[2]['position']['y'])
        self.assertNoOverlap(nodes)

    def test_nested_visual_containers_and_ordinary_parents_share_correct_scope(self):
        nodes = [node('frame', kind='group'), node('q', parentId='frame'), node('finding', parentId='q'),
                 node('subgroup', parentId='frame', isContainer=True), node('leaf', parentId='subgroup'), node('outside')]
        layout_nodes(nodes, [edge('q', 'subgroup')], {n['id'] for n in nodes})
        by_id = {n['id']: n for n in nodes}
        self.assertEqual(visual_scope(nodes, by_id['finding']), 'frame')
        self.assertEqual(visual_scope(nodes, by_id['leaf']), 'subgroup')
        self.assertGreater(by_id['finding']['position']['y'], by_id['q']['position']['y'])
        for child in nodes:
            scope = visual_scope(nodes, child)
            if scope:
                self.assertGreaterEqual(child['position']['x'], by_id[scope]['position']['x'] + 30)
                self.assertGreaterEqual(child['position']['y'], by_id[scope]['position']['y'] + 100)
        self.assertNoOverlap(nodes)

    def test_manual_descendants_anchor_automatic_container(self):
        nodes = [node('frame', kind='group', position={'x': 400, 'y': 100}),
                 node('manual', parentId='frame', position={'x': 430, 'y': 200}, positionSource='manual'), node('outside')]
        before = copy.deepcopy(nodes[:2])
        layout_nodes(nodes, [], {'outside'})
        self.assertEqual(nodes[:2], before)
        self.assertNoOverlap(nodes)

    def test_large_sibling_fan_and_deep_containers_have_no_search_or_recursion_limit(self):
        nodes = [node(str(index)) for index in range(300)]
        layout_nodes(nodes, [edge('0', str(index)) for index in range(1, 300)], {n['id'] for n in nodes})
        self.assertEqual(len({n['position']['x'] for n in nodes[1:]}), 299)
        self.assertEqual(len({n['position']['y'] for n in nodes[1:]}), 1)
        row = sorted(n['position']['x'] for n in nodes[1:])
        self.assertTrue(all(second - first >= WIDTH + GAP for first, second in zip(row, row[1:])))
        nested = [node(str(index), parentId=str(index - 1) if index else None, kind='group') for index in range(120)]
        layout_nodes(nested, [], {n['id'] for n in nested})
        for index, current in enumerate(nested[1:], 1):
            self.assertGreaterEqual(current['position']['x'], nested[index - 1]['position']['x'] + 30)
            self.assertGreaterEqual(current['position']['y'], nested[index - 1]['position']['y'] + 100)


class StorePlacementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'data')
        self.store.create_project({'id': 'study', 'name': 'Study'})

    def tearDown(self):
        self.temp.cleanup()

    def apply(self, operations, **extra):
        return self.store.batch('study', {'operations': operations, **extra})

    def add(self, key, **data):
        return {'op': 'node.add', 'data': {'id': key, 'title': key, **data}}

    def connect(self, source, target, **data):
        return {'op': 'edge.add', 'data': {**edge(source, target), **data}}

    def test_incremental_branch_retains_existing_chain_and_metadata_edits_do_not_move(self):
        p = self.apply([self.add('a'), self.add('b'), self.add('d'), self.connect('a', 'b'), self.connect('b', 'd')])
        old = {n['id']: n['position'] for n in p['nodes']}
        p = self.apply([self.add('c'), self.connect('a', 'c')])
        positions = {n['id']: n['position'] for n in p['nodes']}
        self.assertEqual({key: positions[key] for key in old}, old)
        self.assertEqual(positions['b']['y'], positions['c']['y'])
        self.assertNotEqual(positions['b']['x'], positions['c']['x'])
        self.assertLess(positions['c']['y'], positions['d']['y'])
        self.assertTrue(all(n['positionSource'] == 'auto' for n in p['nodes']))
        revisited = self.apply([self.connect('d', 'a', relation='revisits')])
        self.assertEqual({n['id']: n['position'] for n in revisited['nodes']}, positions)
        edited = self.apply([{'op': 'node.update', 'data': {'id': 'b', 'summary': 'A finding'}}])
        self.assertEqual({n['id']: n['position'] for n in edited['nodes']}, positions)

    def test_late_edges_relayout_auto_nodes_and_manual_pins_never_move(self):
        self.apply([self.add('a'), self.add('b'), self.add('c'), self.add('pin', position={'x': 40, 'y': 322})])
        p = self.apply([self.connect('a', 'b'), self.connect('a', 'c')])
        by_id = {n['id']: n for n in p['nodes']}
        self.assertEqual(by_id['pin']['position'], {'x': 40, 'y': 322})
        self.assertEqual(by_id['pin']['positionSource'], 'manual')
        self.assertEqual(by_id['b']['position']['y'], by_id['c']['position']['y'])
        self.assertGreater(by_id['b']['position']['y'], by_id['a']['position']['y'])
        self.assertGreaterEqual(by_id['b']['position']['x'], 40 + WIDTH + GAP)
        p = self.apply([{'op': 'node.update', 'data': {'id': 'b', 'position': {'x': 700, 'y': 900}}}])
        self.assertEqual(next(n for n in p['nodes'] if n['id'] == 'b')['positionSource'], 'manual')
        self.apply([self.add('next'), self.connect('c', 'next')])
        p = Store(self.root / 'data').get_project('study')
        self.assertEqual(next(n for n in p['nodes'] if n['id'] == 'b')['position'], {'x': 700, 'y': 900})
        before = p
        with self.assertRaises(StoreError):
            self.apply([{'op': 'node.update', 'data': {'id': 'b', 'positionSource': 'guessed'}}])
        self.assertEqual(self.store.get_project('study'), before)

    def legacy(self, key, *, branch=True):
        p = self.store.get_project('study')
        p['id'] = key
        p['nodes'] = [node(value, position={'x': 40, 'y': 40 + 282 * index}) for index, value in enumerate('abc')]
        for n in p['nodes']:
            del n['positionSource']
        p['edges'] = [edge('a', 'b'), edge('a' if branch else 'b', 'c')]
        return p

    def test_exact_legacy_branch_upgrade_is_once_audited_and_old_snapshot_unchanged(self):
        imported = self.store.import_project(self.legacy('legacy'))
        original = copy.deepcopy(imported)
        fixed = self.store.get_project('legacy')
        self.assertEqual(fixed['revision'], original['revision'] + 1)
        self.assertEqual(fixed['nodes'][1]['position']['y'], fixed['nodes'][2]['position']['y'])
        self.assertNotEqual(fixed['nodes'][1]['position']['x'], fixed['nodes'][2]['position']['x'])
        self.assertTrue(all(n['positionSource'] == 'auto' for n in fixed['nodes']))
        self.assertEqual(self.store.get_project('legacy'), fixed)
        self.assertEqual(Store(self.root / 'data').get_project('legacy'), fixed)
        self.assertEqual(self.store.history('legacy')[-1]['operations'], [{'op': 'layout.upgrade'}])
        with self.store._transaction() as db:
            self.assertEqual(self.store._revision(db, 'legacy', original['revision']), original)

    def test_legacy_repair_refuses_approximate_manual_container_and_nonbranch_graphs(self):
        cases = [self.legacy('chain', branch=False), self.legacy('approximate'), self.legacy('manual'),
                 self.legacy('container'), self.legacy('contained')]
        cases[1]['nodes'][1]['position']['x'] += 1
        cases[2]['nodes'][0]['positionSource'] = 'manual'
        cases[3]['nodes'][0]['kind'] = 'group'
        cases[4]['nodes'][1]['parentId'] = 'a'
        for fixture in cases:
            with self.subTest(project=fixture['id']):
                self.assertFalse(legacy_column_candidate(fixture['nodes'], fixture['edges']))
                imported = self.store.import_project(fixture)
                self.assertEqual(self.store.get_project(imported['id']), imported)
        p = self.store.get_project('approximate')
        expected = {n['id']: n['position'] for n in p['nodes']}
        p = self.store.batch('approximate', {'operations': [self.add('new'), self.connect('b', 'new')]})
        self.assertEqual({n['id']: n['position'] for n in p['nodes'] if n['id'] in expected}, expected)

    def test_nested_bounds_reserve_space_for_outside_work_and_manual_children(self):
        p = self.apply([self.add('frame', kind='group', position={'x': 0, 'y': 0}),
                        self.add('q', parentId='frame', position={'x': 30, 'y': 100}),
                        self.add('f', parentId='q', position={'x': 30, 'y': 800}), self.add('outside')])
        LayoutAlgorithmTests().assertNoOverlap(p['nodes'])
        old = {n['id']: n['position'] for n in p['nodes'] if n['positionSource'] == 'manual'}
        p = self.apply([self.add('more', parentId='frame'), self.connect('q', 'more')])
        self.assertEqual({n['id']: n['position'] for n in p['nodes'] if n['id'] in old}, old)
        LayoutAlgorithmTests().assertNoOverlap(p['nodes'])


if __name__ == '__main__':
    unittest.main()
