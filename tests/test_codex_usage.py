"""Native host accounting: measured counters, receipt proof, no chat binding."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from backend.codex_usage import CodexSessionAdapter, recorded_cli_projects
from backend.host_usage import observer_origin

SID = '11111111-2222-3333-4444-555555555555'
AT = '2026-10-22T15:00:'

class CodexUsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.owner = self.root / 'research'
        self.outbox = self.owner / '.exp-observer-runs/outbox'
        self.outbox.mkdir(parents=True)
        directory = self.root / 'codex/sessions/2026/10/22'
        directory.mkdir(parents=True)
        self.path = directory / f'rollout-test-{SID}.jsonl'
        self.events = []
        self.emit('session_meta', {'id':SID,'model_provider':'openai'}, 0)
        self.emit('turn_context', {'model':'actual-model'}, 0)
        self.emit('event_msg', {'type':'task_started'}, 0)
        self.adapter = CodexSessionAdapter([self.root/'codex'])
        self.adapter.outboxes = [self.outbox]
        self.projects = [{'id':'study','nodes':[{'id':'a'}, {'id':'b'}], '_usageRoots':[str(self.owner)]}]

    def emit(self, kind, payload, seconds):
        self.events.append({'type':kind,'timestamp':AT+f'{seconds:02}.000Z','payload':payload})

    def capture(self, node='a', request='r1', project='study'):
        receipt = {'projectId':project,'requestId':request,'nodeId':node}
        task = {'version':1,'state':'synced','url':'http://localhost:4317',**receipt,
                'intent':{'command':'record'},'capturedAt':AT+'05.000Z'}
        (self.outbox/(request+'.json')).write_text(json.dumps(task))
        return receipt

    def call(self, receipt, seconds=5, call_id='c1', *, command=None):
        cmd = command or f'python3 /skill/exp_observer.py record --project {receipt["projectId"]} --title Finding'
        self.emit('response_item', {'type':'function_call','name':'exec_command','call_id':call_id,'arguments':json.dumps({'cmd':cmd})},seconds)
        self.emit('response_item', {'type':'function_call_output','call_id':call_id,'output':json.dumps(receipt)},seconds)

    def tokens(self, ref='response-1', seconds=4, input=100, output=7):
        usage = {'input_tokens':input,'output_tokens':output,'cached_input_tokens':80,'cache_write_input_tokens':0}
        self.emit('token_usage_record', {'response_id':ref,'usage':usage},seconds)
        # The duplicate UI event must never double count an inference.
        self.emit('event_msg', {'type':'token_count','info':{'total_token_usage':usage,'last_token_usage':usage}},seconds)

    def read(self):
        self.path.write_text(''.join(json.dumps(e)+'\n' for e in self.events))
        return self.adapter.read(self.projects)

    def test_long_lived_thread_is_found_by_hint_outside_capture_dates(self):
        receipt = self.capture()
        task_path = self.outbox / 'r1.json'
        task = json.loads(task_path.read_text())
        task['hostUsage'] = {'host':'codex','threadId':SID}
        task_path.write_text(json.dumps(task))
        old = self.root / 'codex/sessions/2026/10/19'
        old.mkdir()
        self.path = old / self.path.name
        self.tokens()
        self.call(receipt, command=r'python.exe -X utf8 -B C:\AgentSkills\exp_observer.py record --project study')
        self.assertEqual(self.read()['study'][0]['inputTokens'], 100)

    def test_legacy_long_thread_without_hint_is_discovered_by_recent_write(self):
        receipt = self.capture()
        old = self.root / 'codex/sessions/2026/10/01'
        old.mkdir()
        self.path = old / self.path.name
        self.tokens()
        self.call(receipt)
        self.assertEqual(self.read()['study'][0]['nodeId'], 'a')

    def test_large_session_is_read_incrementally_and_partial_tail_is_not_lost(self):
        receipt=self.capture()
        self.tokens()
        self.call(receipt)
        with self.path.open('wb') as stream:
            # A sparse oversized irrelevant line models a long transcript
            # without retaining 65 MiB of prose in a test fixture.
            stream.seek(65 * 1024 * 1024)
            stream.write(b'\n')
            stream.write(''.join(json.dumps(e)+'\n' for e in self.events).encode())
        rows=self.adapter.read(self.projects)['study']
        self.assertEqual(len(rows),1)
        partial=json.dumps({'type':'token_usage_record','timestamp':AT+'06.000Z',
                            'payload':{'response_id':'response-2','usage':{'input_tokens':20,'output_tokens':0}}}).encode()
        with self.path.open('ab') as stream:
            stream.write(partial[:len(partial)//2])
        self.assertEqual(len(self.adapter.read(self.projects)['study']),1)
        with self.path.open('ab') as stream:
            stream.write(partial[len(partial)//2:]+b'\n')
            stream.write(json.dumps({'type':'event_msg','timestamp':AT+'07.000Z','payload':{'type':'task_complete'}}).encode()+b'\n')
        rows=self.adapter.read(self.projects)['study']
        self.assertEqual(len(rows),2)
        self.assertEqual(sum(r['inputTokens'] for r in rows),120)

    def test_collection_diagnostics_distinguish_missing_log_unmatched_receipt_and_no_usage(self):
        receipt=self.capture()
        task_path=self.outbox/'r1.json'
        task=json.loads(task_path.read_text())
        task['hostUsage']={'threadId':SID,'host':'codex'}
        task_path.write_text(json.dumps(task))
        with patch('backend.codex_usage.time.monotonic', return_value=0):
            self.adapter.read(self.projects)
        self.assertEqual(self.adapter.diagnostics['study']['state'],'log-not-found')
        self.tokens()
        self.read()
        self.assertEqual(self.adapter.diagnostics['study']['state'],'receipt-unmatched')
        self.call(receipt)
        self.read()
        diagnostic=self.adapter.diagnostics['study']
        self.assertEqual(diagnostic['state'],'collected')
        self.assertEqual(diagnostic['matchedReceipts'],1)
        self.assertEqual(diagnostic['collectedRecords'],1)
        self.events=[e for e in self.events if e['type']!='token_usage_record' and e.get('payload',{}).get('type')!='token_count']
        self.read()
        self.assertEqual(self.adapter.diagnostics['study']['state'],'no-usage')

    def test_native_response_ids_counters_and_cache_are_replayed_once(self):
        receipt = self.capture()
        self.tokens()
        self.call(receipt)
        self.emit('event_msg', {'type':'task_complete'},6)
        rows = self.read()['study']
        self.assertEqual(len(rows),1)
        self.assertEqual({k:rows[0][k] for k in ('inputTokens','outputTokens','cacheReadTokens','nodeId','model')},
                         dict(inputTokens=100,outputTokens=7,cacheReadTokens=80,nodeId='a',model='actual-model'))
        self.assertEqual(rows[0]['attribution'],'recorded-work-window')
        self.assertEqual(rows,self.adapter.read(self.projects)['study'])
        self.tokens('response-2',7,input=120)
        self.assertEqual(len(self.read()['study']),2)

    def test_diagnostic_prose_and_unmatched_receipts_do_not_prove_ownership(self):
        receipt = self.capture()
        self.tokens()
        self.call(receipt, command="python3 -c 'print(\"python3 exp_observer.py record --project study\")'")
        self.assertEqual(self.read(),{})

    def test_one_turn_can_work_on_two_experiments_without_binding_chat(self):
        a = self.capture()
        b = self.capture('b','r2','other')
        self.projects.append({'id':'other','nodes':[{'id':'b'}],'_usageRoots':[str(self.owner)]})
        self.tokens('r1',4)
        self.call(a,5)
        self.call(b,8,'c2')
        self.tokens('r2',9)
        self.call(b,10,'c3')
        rows = self.read()
        self.assertEqual([r['nodeId'] for r in rows['study']],['a'])
        self.assertEqual([r['nodeId'] for r in rows['other']],['b'])
        self.assertNotEqual(rows['study'][0]['sourceRef'],rows['other'][0]['sourceRef'])

    def test_multiple_recordings_in_one_tool_result_leave_ambiguous_node_unassigned(self):
        a=self.capture();b=self.capture('b','r2')
        self.tokens()
        self.call(a)
        self.emit('response_item',{'type':'function_call_output','call_id':'c1','output':json.dumps(b)},5)
        self.assertIsNone(self.read()['study'][0]['nodeId'])

    def test_long_command_poll_receipt_follows_its_original_executor(self):
        receipt = self.capture()
        command = f'text(await tools.exec_command({{cmd:{json.dumps("python3 exp_observer.py execute --project study -- python3 experiment.py")},yield_time_ms:1000}}));'
        self.emit('response_item',{'type':'custom_tool_call','name':'exec','call_id':'start','input':command},2)
        self.tokens(seconds=3)
        self.emit('response_item',{'type':'custom_tool_call_output','call_id':'start','output':[{'type':'input_text','text':json.dumps({'session_id':12345})}]},3)
        self.emit('response_item',{'type':'custom_tool_call','name':'exec','call_id':'poll','input':'text(await tools.write_stdin({session_id:12345,chars:""}));'},4)
        self.emit('response_item',{'type':'custom_tool_call_output','call_id':'poll','output':json.dumps({'output':json.dumps(receipt)})},5)
        self.assertEqual(self.read()['study'][0]['nodeId'],'a')

    def test_fallback_deltas_do_not_sum_repeated_cumulative_totals(self):
        self.call(self.capture())
        for sec,total,last in [(6,100,100),(7,100,100),(8,130,30)]:
            self.emit('event_msg',{'type':'token_count','info':{
                'total_token_usage':{'input_tokens':total,'output_tokens':0},
                'last_token_usage':{'input_tokens':last,'output_tokens':0}}},sec)
        self.emit('event_msg',{'type':'task_complete'},9)
        rows=self.read()['study']
        self.assertEqual(sum(r['inputTokens'] for r in rows),130)
        self.assertEqual(len(rows),2)

    def test_heredoc_prose_is_not_an_invocation_but_cli_with_notes_is(self):
        def parse(cmd):
            return recorded_cli_projects({'name':'exec_command','arguments':json.dumps({'cmd':cmd})})
        self.assertEqual(parse("cat <<'TXT'\npython3 exp_observer.py record --project study\nTXT"),set())
        self.assertEqual(parse("python3 exp_observer.py record --project study --notes \"$(cat <<'TXT'\nraw analysis\nTXT\n)\""),{(observer_origin('http://localhost:4317'),'study')})
        self.assertEqual(parse('python.exe -X utf8 -B C:\\Skills\\exp_observer.py `\n record `\n --project study'),
                         {(observer_origin('http://localhost:4317'), 'study')})
