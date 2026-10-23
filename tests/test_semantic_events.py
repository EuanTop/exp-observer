"""Research changes retain separate identities, independently of command captures."""
import json
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

from backend.store import Store, StoreError
from tests.test_capture import cli, working_directory


class StoreClient(cli.Client):
    """Exercise the real store contract without opening a listening socket."""
    def __init__(self, store):
        super().__init__('http://127.0.0.1:4317')
        self.store = store
        self.offline = False
        self.lose_batch_reply = False

    def request(self, route, body=None, raw=False):
        if self.offline:
            raise cli.ClientError('Offline test transport', code='unavailable')
        parts = [unquote(part) for part in urlsplit(route).path.split('/') if part]
        try:
            if parts == ['api', 'projects'] and body is not None:
                return self.store.create_project(body)
            project = parts[2]
            if len(parts) == 3:
                return self.store.get_project(project)
            if parts[3] == 'batch':
                result = self.store.batch(project, body)
                if self.lose_batch_reply:
                    self.lose_batch_reply = False
                    raise cli.ClientError('Reply lost after commit', code='unavailable')
                return result
            if parts[3] == 'context':
                return self.store.context(project)
            if parts[3] == 'artifacts' and body is not None:
                return self.store.register_artifact(project, body)
        except StoreError as exc:
            raise cli.ClientError(f'{exc.code}: {exc}', code=exc.code, status=exc.status) from exc
        raise AssertionError('Unexpected test transport request: ' + route)


class SemanticEventTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='observer semantic 研究 ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.store = Store(self.root / 'data')
        self.store.create_project({'id': 'study', 'name': 'Isolated semantic study'})
        self.client = StoreClient(self.store)

    def invoke(self, *arguments, cwd=None):
        args = cli.parser().parse_args(['--url', self.client.url, *arguments])
        results = []
        with working_directory(cwd or self.root), patch.object(cli, 'emit', side_effect=results.append):
            code = getattr(cli, args.command)(self.client, args)
        return code, results[-1]

    def project(self):
        return self.store.get_project('study')

    def tasks(self, cwd=None):
        return [json.loads(path.read_text(encoding='utf-8')) for path in
                ((cwd or self.root) / '.exp-observer-runs' / 'outbox').glob('*.json')
                if not path.name.startswith('project-')]

    def test_readable_catalog_metadata_survives_platform_reset_without_init(self):
        # This project was created outside the Skill: only context can preserve
        # its human name. Resuming does not require rerunning the old work.
        self.invoke('context', '--project', 'study')
        self.store = Store(self.root / 'reset-platform')
        self.client.store = self.store
        self.invoke('event', '--project', 'study', '--question', '恢复后继续研究')
        self.assertEqual(self.project()['name'], 'Isolated semantic study')
        self.assertEqual(len(self.project()['nodes']), 1)

    def test_explicit_init_repairs_placeholder_but_preserves_a_real_remote_name(self):
        self.store.batch('study', {'operations': [{'op':'project.update','data':{'name':'study'}}]})
        self.invoke('event', '--project', 'study', '--question', '已有研究')
        self.invoke('init', '--id', 'study', '--name', '可读研究名称')
        self.assertEqual(self.project()['name'], '可读研究名称')
        self.store.batch('study', {'operations': [{'op':'project.update','data':{'name':'用户后来改的名称'}}]})
        self.invoke('init', '--id', 'study', '--name', '可读研究名称')
        self.assertEqual(self.project()['name'], '用户后来改的名称')

    def test_parallel_followups_are_questions_and_importance_applies_to_actual_event(self):
        _, first = self.invoke('event', '--project', 'study', '--question', '中心问题',
                               '--finding', '决定下一步的证据', '--importance', 'critical',
                               '--importance-reason', '隐藏后无法理解研究为什么继续')
        for title in ('后续问题一', '后续问题二', '后续问题三'):
            self.invoke('event', '--project', 'study', '--question', title, '--after', first['nodeId'])
        p = self.project()
        self.assertEqual([n['kind'] for n in p['nodes']].count('question'), 4)
        self.assertFalse(any(n['kind'] == 'direction' for n in p['nodes']))
        finding = next(n for n in p['nodes'] if n['id'] == first['nodeId'])
        self.assertEqual(finding['importance'], 'critical')
        self.assertEqual(finding['importanceReason'], '隐藏后无法理解研究为什么继续')
        self.assertEqual(len([e for e in p['edges'] if e['source'] == first['nodeId'] and e['relation'] == 'branches']), 3)
        self.invoke('record', '--project', 'study', '--title', '研究者自定义观察类型',
                    '--kind', 'ablation_note', '--importance', 'critical')
        self.assertEqual(self.project()['nodes'][-1]['kind'], 'ablation_note')
        self.assertEqual(self.project()['nodes'][-1]['importance'], 'critical')

    def test_same_question_keeps_distinct_findings_correction_and_direction(self):
        _, question = self.invoke('event', '--project', 'study', '--question', '什么影响确认收益？',
            '--reason', '核对用户操作的实际收益。', '--notes', '保留问题的原始范围。')
        _, first = self.invoke('event', '--project', 'study', '--question', question['questionId'],
            '--finding', '符号确认减少错误输入', '--reason', '原始观察显示误输入下降。', '--notes', '首次发现的限制。')
        _, second = self.invoke('event', '--project', 'study', '--question', '什么影响确认收益？',
            '--finding', '导航回退抵消部分收益')
        _, corrected = self.invoke('event', '--project', 'study', '--question', '什么影响确认收益？',
            '--correction', '交付时间需要计入复核成本', '--after', '符号确认减少错误输入')
        _, direction = self.invoke('event', '--project', 'study', '--question', '什么影响确认收益？',
            '--direction', '转向核对错误踏板选择', '--after', corrected['nodeId'], '--status', 'paused')
        self.invoke('event', '--project', 'study', '--question', '什么影响确认收益？', '--reason', '后续引用不重置旧问题。')
        self.assertTrue(all(not receipt['pending'] for receipt in (question, first, second, corrected, direction)))
        self.assertEqual({receipt['questionId'] for receipt in (question, first, second, corrected, direction)},
                         {question['nodeId']})
        nodes = {node['id']: node for node in self.project()['nodes']}
        self.assertEqual(len(nodes), 5)
        self.assertEqual(nodes[question['nodeId']]['notes'], '保留问题的原始范围。')
        self.assertEqual(nodes[question['nodeId']]['summary'], '核对用户操作的实际收益。')
        self.assertEqual(nodes[question['nodeId']]['status'], 'paused')
        self.assertEqual(nodes[first['nodeId']]['conclusion'], '符号确认减少错误输入')
        self.assertEqual(nodes[first['nodeId']]['notes'], '首次发现的限制。')
        self.assertTrue(all(node['parentId'] is None for node in nodes.values()))
        edges = {(edge['source'], edge['target'], edge['relation']) for edge in self.project()['edges']}
        self.assertEqual(edges, {
            (question['nodeId'], first['nodeId'], 'has_finding'),
            (question['nodeId'], second['nodeId'], 'has_finding'),
            (question['nodeId'], corrected['nodeId'], 'has_correction'),
            (question['nodeId'], direction['nodeId'], 'has_direction'),
            (first['nodeId'], corrected['nodeId'], 'revises'),
            (corrected['nodeId'], direction['nodeId'], 'leads_to')})
        self.client.offline = True
        _, context = self.invoke('context', '--project', 'study')
        local_question = next(node for node in context['localNodes'] if node['id'] == question['nodeId'])
        self.assertEqual(local_question['status'], 'paused')
        self.assertEqual(local_question['summary'], '核对用户操作的实际收益。')

    def test_one_capture_supports_several_findings_and_repeated_measurement_reuses_question(self):
        _, question = self.invoke('event', '--project', 'study', '--question', '排序是否稳定？')
        marker = self.root / 'executions.txt'
        program = 'from pathlib import Path; p=Path("executions.txt"); p.write_text(p.read_text()+"x" if p.exists() else "x")'
        _, capture = self.invoke('execute', '--project', 'study', '--title', '原始批量观察',
            '--request-id', 'one-real-batch', '--', sys.executable, '-c', program)
        self.assertFalse(capture['pending'])
        receipts = [self.invoke('event', '--project', 'study', '--question', question['nodeId'],
            '--finding', title, '--evidence', '原始批量观察')[1]
            for title in ('并列输入遵循原始顺序', '错误踏板选择影响确认时间')]
        repeated = ('execute', '--project', 'study', '--question', '排序是否稳定？', '--title', '同问题的重复测量',
                    '--request-id', 'repeated-question', '--', sys.executable, '-c', program)
        _, measurement = self.invoke(*repeated)
        self.assertFalse(measurement['pending'])
        self.assertEqual(measurement['questionId'], question['nodeId'])
        self.assertEqual(marker.read_text(), 'xx')
        self.invoke(*repeated)
        self.assertEqual(marker.read_text(), 'xx')
        self.assertEqual(len(self.project()['nodes']), 4)
        self.assertEqual(len(self.project()['runs']), 2)
        self.assertEqual({edge['target'] for edge in self.project()['edges']
                          if edge['source'] == capture['nodeId'] and edge['relation'] == 'supports'},
                         {receipt['nodeId'] for receipt in receipts})
        self.assertEqual(next(node for node in self.project()['nodes'] if node['id'] == capture['nodeId'])['title'],
                         '原始批量观察')

    def test_disconnected_directories_share_exact_question_identity_without_overwriting_metadata(self):
        folders = [self.root / name for name in ('first', 'second')]
        for folder in folders:
            folder.mkdir()
        self.client.offline = True
        receipts = [self.invoke('event', '--project', 'study', '--question', 'Exact Question', '--reason', reason,
                               '--finding', reason, cwd=folder)[1]
                    for folder, reason in zip(folders, ('First retained discovery', 'Second retained discovery'))]
        self.assertEqual(receipts[0]['questionId'], receipts[1]['questionId'])
        frozen = [self.tasks(folder)[0]['operations'] for folder in folders]
        self.assertEqual(frozen[0][0]['op'], 'node.ensure')
        self.assertEqual(self.project()['nodes'], [])
        self.client.offline = False
        for folder in reversed(folders):
            self.assertEqual(self.invoke('sync', '--project', 'study', cwd=folder)[0], 0)
        self.assertEqual(len(self.project()['nodes']), 3)
        question = next(node for node in self.project()['nodes'] if node['id'] == receipts[0]['questionId'])
        self.assertEqual(question['summary'], 'Second retained discovery')
        self.assertEqual([self.tasks(folder)[0]['operations'] for folder in folders], frozen)
        _, different = self.invoke('event', '--project', 'study', '--question', 'exact question')
        self.assertNotEqual(different['questionId'], question['id'])

    def test_retry_after_lost_reply_and_missing_notes_uses_frozen_event(self):
        source = self.root / 'existing analysis.txt'
        source.write_bytes('完整分析\r\n本次纠正的限制。\r\n'.encode('utf-8'))
        arguments = ('event', '--project', 'study', '--question', '计量边界是否完整？',
                     '--correction', '补计复核开销', '--notes-file', str(source), '--request-id', 'frozen-correction')
        self.client.lose_batch_reply = True
        _, pending = self.invoke(*arguments)
        self.assertTrue(pending['pending'])
        frozen = self.tasks()[0]
        self.assertEqual(len(self.project()['nodes']), 2)
        source.unlink()
        _, acknowledged = self.invoke(*arguments)
        self.assertFalse(acknowledged['pending'])
        self.assertEqual(acknowledged['nodeId'], pending['nodeId'])
        self.assertEqual(self.tasks()[0]['operations'], frozen['operations'])
        self.assertEqual(len(self.project()['nodes']), 2)
        self.assertEqual(len(self.project()['edges']), 1)
        with patch.object(self.client, 'request', side_effect=AssertionError('Acknowledged retry used HTTP')):
            self.assertEqual(self.invoke(*arguments)[1], acknowledged)
        changed = list(arguments)
        changed[changed.index('--correction') + 1] = '不同纠正'
        with self.assertRaisesRegex(cli.ClientError, 'different work'):
            self.invoke(*changed)

    def test_offline_event_freezes_metrics_analysis_and_evidence_with_both_nodes_in_context(self):
        source = self.root / 'measurements.json'
        metrics = {'delivery': {'verification_ms': [2, 3], 'unknown': None}}
        original = json.dumps(metrics, ensure_ascii=False).encode('utf-8')
        source.write_bytes(original)
        notes = '计量包含复核。\r\n限制：仅当前样本。\r\n'
        self.client.offline = True
        _, receipt = self.invoke('event', '--project', 'study', '--question', '交付成本如何计量？',
            '--correction', '复核属于交付成本', '--notes', notes, '--metrics-file', str(source), '--artifact', str(source))
        self.assertTrue(receipt['pending'])
        frozen = self.tasks()[0]['operations']
        source.write_text('changed after capture', encoding='utf-8')
        self.client.offline = False
        _, context = self.invoke('context', '--project', 'study')
        self.assertEqual({node['id'] for node in context['localPendingNodes']},
                         {receipt['questionId'], receipt['nodeId']})
        self.assertEqual(self.invoke('sync', '--project', 'study')[0], 0)
        project = self.project()
        self.assertEqual(project['runs'][0]['metrics'], metrics)
        self.assertEqual(project['runs'][0]['nodeId'], receipt['nodeId'])
        self.assertEqual(next(node for node in project['nodes'] if node['id'] == receipt['nodeId'])['notes'], notes)
        self.assertEqual(Path(project['artifacts'][0]['path']).read_bytes(), original)
        self.assertEqual(self.tasks()[0]['operations'], frozen)
        self.assertEqual(list(self.root.rglob('*.md')), [])

    def test_exact_ancestor_and_cached_references_reuse_legacy_questions(self):
        _, legacy = self.invoke('record', '--project', 'study', '--title', '旧问题的自然标题',
                                '--kind', 'question', '--notes', '原始分析')
        child = self.root / 'child'
        child.mkdir()
        self.client.offline = True
        _, first = self.invoke('event', '--project', 'study', '--question', '旧问题的自然标题',
                               '--finding', '新证据需要独立保留', cwd=child)
        self.assertEqual(first['questionId'], legacy['nodeId'])
        self.client.offline = False
        self.assertEqual(self.invoke('sync', '--project', 'study', cwd=child)[0], 0)
        self.assertEqual(len(self.project()['nodes']), 2)
        self.assertEqual(self.project()['nodes'][0]['notes'], '原始分析')
        self.store.batch('study', {'operations': [{'op': 'node.add', 'data': {
            'id': 'remote-question', 'title': '上下文中已有的问题', 'kind': 'question', 'status': 'completed'}}]})
        self.invoke('context', '--project', 'study')
        self.client.offline = True
        _, cached = self.invoke('event', '--project', 'study', '--question', '上下文中已有的问题',
                                '--finding', '离线也能引用保留的上下文', cwd=child)
        self.assertEqual(cached['questionId'], 'remote-question')
        _, offline_context = self.invoke('context', '--project', 'study', cwd=child)
        nodes = {node['id']: node for node in offline_context['localNodes']}
        self.assertEqual(nodes[cached['nodeId']]['kind'], 'finding')

    def test_ambiguous_titles_and_missing_prose_references_do_not_invent_relationships(self):
        for unused in range(2):
            self.invoke('record', '--project', 'study', '--title', '相同标题', '--kind', 'question')
        before = len(self.tasks())
        with self.assertRaisesRegex(cli.ClientError, 'ambiguous'):
            self.invoke('event', '--project', 'study', '--question', '相同标题', '--finding', '不能猜测归属')
        self.assertEqual(len(self.tasks()), before)
        _, retained = self.invoke('event', '--project', 'study', '--question', '明确问题', '--finding', '证据不足',
                                  '--after', '本地从未记录的旧发现', '--evidence', '相同标题')
        self.assertFalse(retained['pending'])
        self.assertEqual(len(retained['recordingWarnings']), 2)
        self.assertEqual([edge['relation'] for edge in self.project()['edges'] if edge['target'] == retained['nodeId']],
                         ['has_finding'])
        _, receipt = self.invoke('event', '--project', 'study', '--question', '明确问题',
                                 '--finding', '正文提到旧发现也不猜测因果')
        self.assertEqual([edge['relation'] for edge in self.project()['edges'] if edge['target'] == receipt['nodeId']],
                         ['has_finding'])

    def test_last_finding_can_park_only_its_question_and_omitted_fields_survive(self):
        self.client.offline = True
        _, other = self.invoke('event', '--project', 'study', '--question', 'Other work stays active')
        arguments = ('event', '--project', 'study', '--question', 'What remains uncertain?',
                     '--finding', 'The measured scope is narrower than expected', '--status', 'paused',
                     '--next-action', 'Collect the missing condition', '--pause-reason', 'No remaining budget',
                     '--resume-when', 'A new sample is available', '--request-id', 'last-real-finding')
        _, final = self.invoke(*arguments)
        frozen = next(task for task in self.tasks() if task['requestId'] == 'last-real-finding')
        update = next(op['data'] for op in frozen['operations'] if op['op'] == 'node.update')
        self.assertEqual(update, {'id': final['questionId'], 'status': 'paused',
                                 'nextAction': 'Collect the missing condition', 'pauseReason': 'No remaining budget',
                                 'resumeWhen': 'A new sample is available'})
        self.invoke('event', '--project', 'study', '--question', 'What remains uncertain?',
                    '--finding', 'The same retained scope also explains the outlier')
        outbox = self.root / '.exp-observer-runs' / 'outbox'
        nodes = {node['id']: node for node in cli.local_nodes(self.client, outbox, 'study')}
        self.assertEqual(nodes[final['questionId']]['title'], 'What remains uncertain?')
        self.assertEqual(nodes[final['questionId']]['status'], 'paused')
        self.assertEqual(nodes[other['questionId']]['status'], 'active')
        _, local = self.invoke('context', '--project', 'study')
        question = next(node for node in local['localNodes'] if node['id'] == final['questionId'])
        self.assertEqual((question['nextAction'], question['pauseReason'], question['resumeWhen']),
                         ('Collect the missing condition', 'No remaining budget', 'A new sample is available'))
        _, status = self.invoke('status', '--project', 'study')
        self.assertEqual([q['id'] for q in status['researchReview']['openQuestions']], [other['questionId']])
        self.assertTrue(status['researchReview']['needsReview'])
        self.client.offline = False
        self.assertEqual(self.invoke('sync', '--project', 'study')[0], 0)
        self.invoke(*arguments)
        nodes = {node['id']: node for node in self.project()['nodes']}
        self.assertEqual(nodes[final['questionId']]['pauseReason'], 'No remaining budget')
        self.assertEqual(nodes[other['questionId']]['status'], 'active')
        self.assertEqual(next(task for task in self.tasks() if task['requestId'] == 'last-real-finding')['operations'],
                         frozen['operations'])
        completed = ('event', '--project', 'study', '--question', 'What remains uncertain?',
                     '--finding', 'The new sample resolves this question', '--status', 'completed')
        self.invoke(*completed)
        question = next(n for n in self.project()['nodes'] if n['id'] == final['questionId'])
        self.assertEqual(question['status'], 'completed')
        self.assertEqual(question['nextAction'], 'Collect the missing condition')
        self.assertEqual(len([n for n in self.project()['nodes'] if n['kind'] == 'question']), 2)

    def test_new_closeout_fields_preserve_old_frozen_retry_and_reject_changed_intent(self):
        self.client.offline = True
        legacy = ('event', '--project', 'study', '--question', 'Legacy retry', '--finding', 'Retained finding',
                  '--request-id', 'old-format')
        self.invoke(*legacy)
        path = next(path for path in (self.root / '.exp-observer-runs' / 'outbox').glob('*.json')
                    if json.loads(path.read_text()).get('requestId') == 'old-format')
        old = json.loads(path.read_text())
        for field in ('next_action', 'pause_reason', 'resume_when'):
            old['intent'].pop(field)
        cli.save_task(path, old)
        self.client.offline = False
        _, receipt = self.invoke(*legacy)
        self.assertFalse(receipt['pending'])
        self.assertEqual(json.loads(path.read_text())['operations'], old['operations'])
        with self.assertRaisesRegex(cli.ClientError, 'different work'):
            self.invoke(*legacy, '--next-action', 'A different retry')
        paused = ('event', '--project', 'study', '--question', 'Frozen paused question', '--finding', 'Latest finding',
                  '--status', 'paused', '--next-action', 'Read the retained evidence', '--request-id', 'paused-intent')
        self.client.lose_batch_reply = True
        _, queued = self.invoke(*paused)
        self.assertTrue(queued['pending'])
        _, receipt = self.invoke(*paused)
        self.assertFalse(receipt['pending'])
        with self.assertRaisesRegex(cli.ClientError, 'different work'):
            self.invoke(*paused, '--pause-reason', 'Changed work')

    def write_cache(self, nodes, at, cwd=None, node_id=None, project_id='study', url=None):
        folder = (cwd or self.root) / '.exp-observer-runs' / 'context'
        folder.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(json.dumps([url or self.client.url, project_id, node_id],
                                       ensure_ascii=False).encode('utf-8')).hexdigest()
        path = folder / (key + '.json')
        path.write_text(json.dumps({'cachedAt': at, 'nodeId': node_id,
                                   'context': {'projectId': project_id, 'nodes': nodes}}), encoding='utf-8')
        return path

    def test_newer_dated_cache_overrides_old_synced_but_pending_patch_overlays_cache(self):
        _, opened = self.invoke('event', '--project', 'study', '--question', 'Exact retained question')
        outbox = self.root / '.exp-observer-runs' / 'outbox'
        for path in outbox.glob('*.json'):
            task = json.loads(path.read_text())
            if task.get('kind') != 'project':
                task['capturedAt'] = '2020-01-01T00:00:00Z'
                cli.save_task(path, task)
        cache = {'id': opened['questionId'], 'title': 'Exact retained question', 'kind': 'question',
                 'status': 'completed', 'nextAction': 'Remote completed step', 'pauseReason': ''}
        self.write_cache([cache], '2021-01-01T00:00:00Z')
        self.client.offline = True
        _, state = self.invoke('status', '--project', 'study')
        self.assertEqual(state['researchReview']['openQuestions'], [])
        self.assertFalse(state['researchReview']['needsReview'])
        self.assertEqual(state['researchReview']['cachedContexts'][0]['cachedAt'], '2021-01-01T00:00:00Z')
        self.invoke('event', '--project', 'study', '--question', 'Exact retained question',
                    '--finding', 'Supplement without reopening')
        nodes = cli.semantic_nodes(self.client, outbox, 'study')
        self.assertEqual(next(n for n in nodes if n['id'] == opened['questionId'])['status'], 'completed')
        self.invoke('event', '--project', 'study', '--question', opened['questionId'],
                    '--status', 'active', '--next-action', 'Investigate a new counterexample', '--request-id', 'new-intent')
        # A later fetch can omit a not-yet-delivered intent. The pending patch
        # remains visible while earlier synced operations must not reset it.
        self.write_cache([cache], '2099-01-01T00:00:00Z')
        _, state = self.invoke('status', '--project', 'study')
        question = state['researchReview']['openQuestions'][0]
        self.assertEqual((question['id'], question['title'], question['status'], question['nextAction']),
                         (opened['questionId'], 'Exact retained question', 'active', 'Investigate a new counterexample'))
        self.assertEqual(state['deliveryState'], 'pending')
        self.assertEqual(state['researchReview']['coverage'], 'local_snapshot_only')

    def test_status_reads_only_ancestor_queues_and_dated_context_without_mutations(self):
        self.client.offline = True
        _, ancestor = self.invoke('event', '--project', 'study', '--question', 'Ancestor question',
                                  '--next-action', 'Keep measuring')
        child, sibling = self.root / 'child', self.root / 'sibling'
        child.mkdir()
        sibling.mkdir()
        self.invoke('event', '--project', 'study', '--question', 'Sibling question', cwd=sibling)
        self.invoke('event', '--project', 'other-study', '--question', 'Other experiment', cwd=child)
        self.write_cache([{'id': 'cached-question', 'title': 'Cached running question', 'kind': 'question',
                           'status': 'running', 'nextAction': 'Wait for actual result'}],
                          '2020-01-01T00:00:00Z', node_id='cached-question')
        self.write_cache([{'id': 'sibling-cache', 'title': 'Sibling cache', 'kind': 'question', 'status': 'active'}],
                          '2022-01-01T00:00:00Z', cwd=sibling)
        before = {str(path): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        with patch.object(self.client, 'request', side_effect=AssertionError('status used HTTP')), \
             patch.object(cli, 'save_task', side_effect=AssertionError('status wrote a task')), \
             patch.object(cli, 'task_lock', side_effect=AssertionError('status used a lock')), \
             patch.object(cli.subprocess, 'Popen', side_effect=AssertionError('status ran a command')), \
             patch.object(Path, 'rglob', side_effect=AssertionError('status recursively searched directories')):
            _, state = self.invoke('status', '--project', 'study', cwd=child)
            _, unknown = self.invoke('status', '--project', 'unknown', cwd=child)
        review = state['researchReview']
        self.assertEqual({q['id'] for q in review['openQuestions']}, {ancestor['questionId'], 'cached-question'})
        self.assertEqual(review['scope'], 'current_directory_and_ancestors')
        self.assertTrue(review['needsReview'])
        self.assertFalse(state['transportChecked'])
        self.assertEqual(unknown['researchReview']['availability'], 'unknown')
        self.assertIsNone(unknown['researchReview']['needsReview'])
        after = {str(path): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        self.assertEqual(before, after)

    def test_cached_closed_question_keeps_its_status_and_followup_in_offline_context(self):
        cached = {'id': 'closed', 'title': 'Completed elsewhere', 'kind': 'question', 'status': 'completed',
                  'nextAction': 'Revisit only for new evidence', 'pauseReason': 'Earlier pause', 'resumeWhen': 'New evidence'}
        self.write_cache([cached], '2020-01-01T00:00:00Z')
        child = self.root / 'child'
        child.mkdir()
        self.client.offline = True
        self.invoke('event', '--project', 'study', '--question', 'Completed elsewhere',
                    '--finding', 'A bounded follow-up finding', cwd=child)
        _, context = self.invoke('context', '--project', 'study', cwd=child)
        question = next(node for node in context['localNodes'] if node['id'] == 'closed')
        self.assertEqual((question['status'], question['nextAction'], question['resumeWhen']),
                         ('completed', 'Revisit only for new evidence', 'New evidence'))
        _, status = self.invoke('status', '--project', 'study', cwd=child)
        self.assertEqual(status['researchReview']['openQuestions'], [])

    def test_full_cache_can_remove_old_synced_nodes_but_missing_status_remains_unknown(self):
        self.invoke('event', '--project', 'study', '--question', 'Old acknowledged question')
        self.write_cache([], '2099-01-01T00:00:00Z')
        _, status = self.invoke('status', '--project', 'study')
        self.assertFalse(status['researchReview']['needsReview'])
        self.assertEqual(status['researchReview']['openQuestions'], [])
        self.write_cache([{'id': 'unknown', 'title': 'No status in old cache', 'kind': 'question'}],
                         '2099-01-01T00:00:00Z')
        _, status = self.invoke('status', '--project', 'study')
        self.assertIsNone(status['researchReview']['needsReview'])
        self.assertEqual(status['researchReview']['availability'], 'partial')

    def test_undated_cache_does_not_claim_known_research_state(self):
        self.write_cache([{'id': 'unknown', 'title': 'Question', 'kind': 'question', 'status': 'completed'}], None)
        self.client.offline = True
        _, result = self.invoke('status', '--project', 'study')
        self.assertEqual(result['deliveryState'], 'unknown')
        self.assertEqual(result['researchReview']['availability'], 'partial')
        self.assertIsNone(result['researchReview']['needsReview'])
        self.assertEqual(result['researchReview']['openQuestions'], [])
        self.assertIn('date', result['researchReview']['localReadWarnings'][0])

    def test_existing_alias_remains_a_reference_without_recreating_or_resetting_merged_question(self):
        _, original = self.invoke('record', '--project', 'study', '--title', '待合并的旧问题', '--kind', 'question')
        self.store.batch('study', {'operations': [
            {'op': 'node.add', 'data': {'id': 'retained', 'title': '合并后的问题', 'kind': 'question',
                                      'status': 'completed', 'conclusion': '保留已完成的判断'}},
            {'op': 'node.merge', 'data': {'id': original['nodeId'], 'target': 'retained'}}]})
        _, finding = self.invoke('event', '--project', 'study', '--question', '待合并的旧问题',
                                 '--finding', '合并后的补充发现')
        self.assertFalse(finding['pending'])
        self.assertEqual(len(self.project()['nodes']), 2)
        retained = next(node for node in self.project()['nodes'] if node['id'] == 'retained')
        self.assertEqual((retained['title'], retained['status'], retained['conclusion']),
                         ('合并后的问题', 'completed', '保留已完成的判断'))
        self.assertEqual(self.project()['edges'][0]['source'], 'retained')


if __name__ == '__main__':
    unittest.main()