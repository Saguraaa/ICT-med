import copy
import json
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agents import Budget, BudgetExceeded, ModelClient, ModelOutputError, demo_response, parse_object
from config import ROOT, Settings
from local_app import make_handler
from medroute import InputError, MedRoute, validate_input
from retrieval import Retriever
from service import handle_payload


class RecordingModel:
    def __init__(self, transform=None):
        self.calls = []
        self.transform = transform

    def complete(self, task, payload, budget):
        budget.before_call(task)
        self.calls.append((task, copy.deepcopy(payload)))
        result = demo_response(task, payload)
        if self.transform:
            self.transform(task, payload, result)
        return result


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(backend='demo')
        (ROOT / 'work').mkdir(exist_ok=True)

    def run_case(self, text='demo', model=None, **settings):
        return MedRoute(replace(self.settings, **settings), model=model).run({'message': text})

    def test_single(self):
        result = self.run_case()
        self.assertEqual((result['status'], result['route']), ('completed', 'single'))
        self.assertEqual(result['metrics']['model_calls'], 4)
        self.assertTrue(result['response'].startswith('【离线演示】'))

    def test_multi_and_early_stop(self):
        result = self.run_case('demo [demo:moderate]')
        self.assertEqual(result['route'], 'multi')
        self.assertEqual(len(result['reports']), 3)
        reviews = [e for e in result['trace'] if e['event'] == 'discussion_review']
        self.assertEqual(len(reviews), 1)

    def test_high_passes_all_reports_to_final_and_review(self):
        model = RecordingModel()
        result = self.run_case('demo [demo:high]', model)
        self.assertEqual(result['route'], 'multi_team')
        final_payload = next(p for task, p in model.calls if task == 'final')
        self.assertEqual(len(final_payload['reports']), 5)
        final_team = next(p for task, p in model.calls
                          if task == 'expert' and p['stage'] == 'final_review_team')
        self.assertEqual(len(final_team['previous_reports']), 4)

    def test_rule_escalates_without_model_calls(self):
        result = self.run_case('demo [demo:redflag]')
        self.assertEqual(result['route'], 'safety_escalation')
        self.assertEqual(result['metrics']['model_calls'], 0)
        self.assertEqual(result['handoff']['transfer_status'], 'not_connected')

    def test_model_escalation_overrides_high_complexity(self):
        result = self.run_case('demo [demo:urgent] [demo:high]')
        self.assertEqual(result['route'], 'safety_escalation')
        self.assertEqual(result['reports'], [])

    def test_new_expert_risk_interrupts_remaining_experts(self):
        def change(task, payload, result):
            if task == 'expert':
                result['needs_escalation'] = True
        result = self.run_case('demo [demo:moderate]', RecordingModel(change))
        self.assertEqual(result['status'], 'escalated')
        self.assertEqual(len(result['reports']), 1)
        self.assertEqual(result['metrics']['model_calls'], 2)

    def test_followup_rechecks_risk(self):
        svc = MedRoute(self.settings)
        first = svc.run({'message': 'demo [demo:clarify]'})
        self.assertEqual(first['status'], 'need_more_info')
        second = svc.run({'message': '[demo:complete]', 'case_state': first['case_state']})
        self.assertEqual(second['route'], 'single')
        third = svc.run({'message': '[demo:urgent]', 'case_state': second['case_state']})
        self.assertEqual(third['route'], 'safety_escalation')

    def test_sessions_do_not_share_messages(self):
        svc = MedRoute(self.settings)
        svc.run({'message': 'demo [demo:urgent]'}, session_id='a')
        second = svc.run({'message': 'demo'}, session_id='b')
        self.assertEqual(second['route'], 'single')
        self.assertEqual(second['case_state']['user_messages'], ['demo'])

    def test_call_budget_fails_closed(self):
        result = self.run_case(max_calls=1)
        self.assertEqual(result['handoff']['reason'], 'model_call_limit')
        self.assertEqual(result['metrics']['model_calls'], 1)
        self.assertEqual(result['claims'], [])

    def test_deadline_fails_closed(self):
        budget = Budget(self.settings)
        budget.deadline = 0
        with self.assertRaises(BudgetExceeded):
            budget.before_call('triage')
        self.assertEqual(budget.calls, 0)

    def test_forged_reference_blocks_final(self):
        def change(task, payload, result):
            if task == 'final':
                result['claims'][0]['evidence_ids'] = ['made-up-source']
        result = self.run_case(model=RecordingModel(change))
        self.assertEqual(result['handoff']['reason'], 'citation_integrity_failed')

    def test_unsupported_reference_blocks_final(self):
        def change(task, payload, result):
            if task == 'verify':
                result['supported'], result['issues'] = False, ['原文不支持建议']
        result = self.run_case(model=RecordingModel(change))
        self.assertEqual(result['handoff']['reason'], 'evidence_support_failed')

    def test_expert_uncertainty_is_not_consensus(self):
        def change(task, payload, result):
            if task == 'expert':
                result['uncertainties'] = ['未解决']
        result = self.run_case('demo [demo:moderate]', RecordingModel(change))
        self.assertEqual(result['handoff']['reason'], 'discussion_limit_unresolved')

    def test_next_round_receives_all_previous_opinions(self):
        def change(task, payload, result):
            if task == 'moderator':
                result['stop'] = False
        model = RecordingModel(change)
        self.run_case('demo [demo:moderate]', model)
        second = [p for task, p in model.calls
                  if task == 'expert' and p['stage'] == 'specialist_round_2']
        self.assertEqual(len(second), 3)
        self.assertTrue(all(len(p['previous_opinions']) == 3 for p in second))

    def test_invalid_classifier_does_not_default_to_easy(self):
        def change(task, payload, result):
            if task == 'triage':
                result['complexity'] = 'nonsense'
        result = self.run_case(model=RecordingModel(change))
        self.assertEqual(result['handoff']['reason'], 'invalid_triage')

    def test_schema_diagnostics_do_not_expose_model_values(self):
        def change(task, payload, result):
            if task == 'triage':
                result['risk'] = 'private-model-text'
                result['questions'] = None
                result['needs_clarification'] = 'false'
        result = self.run_case(model=RecordingModel(change))
        errors = result['diagnostics']['validation_errors']
        self.assertEqual(set(errors), {'risk', 'questions', 'needs_clarification'})
        self.assertNotIn('private-model-text', json.dumps(errors))
        self.assertEqual(result['handoff']['reason'], 'invalid_triage')

    def test_deepseek_json_mode_request_and_opt_out(self):
        response = {'choices': [{'message': {'content': '{"ok":true}'}}]}
        cases = [('https://api.deepseek.com', 'auto', True),
                 ('https://api.deepseek.com', 'false', False),
                 ('https://example.org/v1', 'auto', False),
                 ('https://example.org/v1', 'true', True)]
        for url, mode, expected in cases:
            with self.subTest(url=url, mode=mode):
                cfg = replace(self.settings, backend='openai', model='test-model', api_key='test-only',
                              model_url=url, json_mode=mode)
                with patch('agents.post_json', return_value=response) as post:
                    ModelClient(cfg).complete('triage', {'messages': ['test']}, Budget(cfg))
                body = post.call_args.args[1]
                self.assertEqual('response_format' in body, expected)
                if expected:
                    self.assertEqual(body['response_format'], {'type': 'json_object'})

    def test_baselines_preserve_risk_gate(self):
        for strategy in ('single', 'fixed_multi'):
            with self.subTest(strategy=strategy):
                self.assertEqual(self.run_case('demo [demo:urgent]', routing_strategy=strategy)['route'],
                                 'safety_escalation')
        self.assertEqual(self.run_case('demo [demo:high]', routing_strategy='single')['route'], 'single')
        self.assertEqual(self.run_case('demo', routing_strategy='fixed_multi')['route'], 'multi')

    def test_empty_and_invalid_inputs(self):
        for payload in ({}, [], {'message': ''}, {'message': 2},
                        {'message': 'x', 'case_state': {'user_messages': ['x'] * 12}}):
            with self.subTest(payload=payload), self.assertRaises(InputError):
                validate_input(payload)
        self.assertEqual(handle_payload({})['error'], 'invalid_input')

    def test_json_parser_never_executes_code(self):
        with self.assertRaises(ModelOutputError):
            parse_object("__import__('os').getcwd()")
        self.assertEqual(parse_object('```json\n{"x": 1}\n```'), {'x': 1})

    def test_live_does_not_use_demo_corpus(self):
        cfg = replace(self.settings, backend='openai')
        docs = Retriever(cfg).search('demo', Budget(cfg))
        self.assertEqual(docs, [])

    def test_missing_model_key_hands_off(self):
        result = self.run_case(backend='openai')
        self.assertEqual(result['handoff']['reason'], 'model_not_configured')

    def test_live_release_requires_reviewed_rules_and_explicit_flag(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'work') as temp:
            knowledge = Path(temp) / 'knowledge.jsonl'
            knowledge.write_text(json.dumps({
                'id': 'test-real', 'title': 'demo test', 'content': 'demo test evidence',
                'source': 'https://example.org/test-only', 'updated_at': '2026-10-28',
                'reviewed': True, 'demo': False,
            }), encoding='utf-8')
            cfg = replace(self.settings, backend='openai', knowledge_path=knowledge,
                          enable_triage_output=True)
            result = MedRoute(cfg, model=RecordingModel()).run({'message': 'demo'})
            self.assertEqual(result['handoff']['reason'], 'clinical_release_disabled_or_rules_unreviewed')

    def test_missing_knowledge_does_not_guess(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'work') as temp:
            result = self.run_case(knowledge_path=Path(temp) / 'missing.jsonl')
            self.assertEqual(result['handoff']['reason'], 'knowledge_file_unavailable')

    def test_unretrieved_expert_reference_is_rejected(self):
        def change(task, payload, result):
            if task == 'expert':
                result['evidence_ids'] = ['invented']
        result = self.run_case(model=RecordingModel(change))
        self.assertEqual(result['handoff']['reason'], 'expert_unknown_citation')


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(backend='demo', api_token='test-secret')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.settings))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def post(self, body, token='test-secret', content_type='application/json'):
        req = Request(self.url + '/invocations', body, {
            'Content-Type': content_type, 'Authorization': 'Bearer ' + token}, method='POST')
        return urlopen(req, timeout=10)

    def test_health_and_real_http_invocation(self):
        with urlopen(self.url + '/ping') as response:
            self.assertEqual(json.load(response)['mode'], 'demo')
        with self.post(b'{"message":"demo [demo:high]"}') as response:
            self.assertEqual(json.load(response)['route'], 'multi_team')

    def test_auth(self):
        with self.assertRaises(HTTPError) as err:
            self.post(b'{"message":"demo"}', token='wrong')
        self.assertEqual(err.exception.code, 401)

    def test_invalid_json_and_input(self):
        for body in (b'{invalid', b'{}'):
            with self.assertRaises(HTTPError) as err:
                self.post(body)
            self.assertEqual(err.exception.code, 400)

    def test_content_type(self):
        with self.assertRaises(HTTPError) as err:
            self.post(b'{}', content_type='text/plain')
        self.assertEqual(err.exception.code, 415)

    def test_openai_compatible_request_uses_configured_model(self):
        captured = {}

        class ModelHandler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                captured['path'] = self.path
                captured['auth'] = self.headers.get('Authorization')
                captured['body'] = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                data = json.dumps({'choices': [{'message': {'content': '{"ok":true}'}}],
                                   'usage': {'prompt_tokens': 7, 'completion_tokens': 3}}).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        server = ThreadingHTTPServer(('127.0.0.1', 0), ModelHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            cfg = replace(self.settings, backend='openai', model='my-real-model', api_key='private-test',
                          model_url=f'http://127.0.0.1:{server.server_port}/v1')
            budget = Budget(cfg)
            # Environment proxy should not intercept local test requests.
            with patch.dict('os.environ', {'NO_PROXY': '127.0.0.1,localhost'}):
                result = ModelClient(cfg).complete('triage', {'messages': ['test']}, budget)
            self.assertEqual(result, {'ok': True})
            self.assertEqual(captured['path'], '/v1/chat/completions')
            self.assertEqual(captured['body']['model'], 'my-real-model')
            self.assertEqual(budget.input_tokens, 7)
            self.assertEqual(budget.output_tokens, 3)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_external_retrieval_contract_filters_unreviewed_sources(self):
        captured = {}

        class RetrievalHandler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                captured.update(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                document = {'id': 'reviewed', 'title': 'test', 'content': 'test evidence',
                            'source': 'https://example.org/fixture', 'updated_at': '2026-10-28',
                            'reviewed': True, 'demo': False}
                data = json.dumps({'documents': [document, document | {
                    'id': 'unreviewed', 'reviewed': False}]}).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        server = ThreadingHTTPServer(('127.0.0.1', 0), RetrievalHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            cfg = replace(self.settings, backend='openai',
                          retrieval_url=f'http://127.0.0.1:{server.server_port}/retrieve')
            with patch.dict('os.environ', {'NO_PROXY': '127.0.0.1,localhost'}):
                documents = Retriever(cfg).search('test question', Budget(cfg))
            self.assertEqual(captured, {'query': 'test question', 'top_k': 4})
            self.assertEqual([d['id'] for d in documents], ['reviewed'])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
