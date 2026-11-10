import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from agents import Budget, ModelOutputError, ServiceFailure, demo_response
from benchmark import run_suite
from collaboration import validate_action, select_roles, build_context
from config import Settings
from evidence_loop import apply_retrieval
from integration import validate_integration
from medroute import MedRoute
from metrics import compare


class Model:
    def __init__(self):
        self.calls = []

    def complete(self, task, payload, budget):
        budget.before_call(task)
        self.calls.append((task, copy.deepcopy(payload)))
        return demo_response(task, payload)


class OptimizationTests(unittest.TestCase):
    def test_emergency_not_downgraded_by_missing_integration(self):
        class Emergency(Model):
            def complete(self, task, payload, budget):
                result = super().complete(task, payload, budget)
                if task == 'final':
                    result['care_level'] = 'emergency'
                    result.pop('integration_decisions', None)
                return result
        result = MedRoute(Settings(backend='demo', integration_policy='evidence_first'),
                          model=Emergency()).run({'message': 'demo'})
        self.assertEqual(result['status'], 'escalated')

    def test_selective_reconsult_calls_only_requested_role(self):
        class Selective(Model):
            def complete(self, task, payload, budget):
                result = super().complete(task, payload, budget)
                if task == 'moderator' and sum(t == task for t, _ in self.calls) == 1:
                    result['stop'] = False
                    result['review_action'] = {'action': 'reconsult', 'selected_roles': ['respiratory'],
                                              'issues': [], 'queries': [], 'questions': []}
                return result
        model = Selective()
        result = MedRoute(Settings(backend='demo', collab_policy='selective'), model=model).run(
            {'message': 'demo [demo:moderate]'})
        self.assertEqual(result['status'], 'completed')
        second = [p for t, p in model.calls if t == 'expert' and p['stage'] == 'specialist_round_2']
        self.assertEqual([p['role'] for p in second], ['呼吸专科'])

    def test_low_complexity_supplement_new_citation(self):
        class Retrieval:
            def __init__(self):
                self.calls = 0
            def search(self, query, budget):
                self.calls += 1
                return [{'id': 'old' if self.calls == 1 else 'new', 'title': 't', 'content': 'c',
                    'source': 's', 'updated_at': '2026', 'reviewed': True, 'demo': False}]
        class Supplement(Model):
            def complete(self, task, payload, budget):
                result = super().complete(task, payload, budget)
                if task == 'expert':
                    result['evidence_ids'] = [payload['evidence'][-1]['id']]
                    result['uncertainties'] = ['gap'] if payload['stage'] == 'primary_care' else []
                if task == 'moderator' and sum(t == task for t, _ in self.calls) == 1:
                    result['stop'] = False
                    result['review_action'] = {'action': 'retrieve', 'queries': ['follow up'],
                        'issues': [{'id': 'i', 'kind': 'knowledge_gap', 'text': 'gap',
                            'affected_roles': ['general'], 'evidence_ids': ['old'], 'status': 'open'}]}
                if task == 'final':
                    result['claims'][0]['evidence_ids'] = ['new']
                return result
        retriever = Retrieval()
        result = MedRoute(Settings(backend='demo', evidence_policy='gap_driven'),
                          model=Supplement(), retriever=retriever).run({'message': 'demo'})
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(retriever.calls, 2)
        self.assertEqual(result['citations'][0]['id'], 'new')

    def test_full_matrix_runs_without_claiming_medical_accuracy(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_suite([{'id': '1', 'message': 'demo [demo:moderate]'}],
                ['B0', 'A', 'B', 'C', 'AB', 'AC', 'BC', 'ABC'], Settings(backend='demo'),
                Path(directory)/'run', repeats=1)
            self.assertTrue(all(r['accuracy'] is None for r in result.values()))
            self.assertTrue((Path(directory)/'run'/'acceptance.md').exists())

    def test_selective_context_preserves_related_and_risk_reports(self):
        issues = [{'id': 'i1', 'status': 'open', 'affected_roles': ['general']}]
        reports = [{'role': 'general', 'uncertainties': ['missing']},
                   {'role': 'digestive', 'uncertainties': []},
                   {'role': 'respiratory', 'needs_escalation': True, 'uncertainties': []}]
        self.assertEqual(select_roles(issues, reports, ['general', 'digestive']), ['general'])
        self.assertEqual([r['role'] for r in build_context('general', reports, issues)], ['general', 'respiratory'])

    def test_invalid_action_and_open_issue_stop_fail_closed(self):
        with self.assertRaises(ModelOutputError):
            validate_action({'action': 'reconsult', 'selected_roles': ['invented']}, ['general'], set())
        with self.assertRaises(ModelOutputError):
            validate_action({'action': 'stop', 'issues': [{'id': 'i', 'kind': 'knowledge_gap',
                'text': 'gap', 'status': 'open'}]}, ['general'], set())

    def test_evidence_collision_and_patient_fact_rejection(self):
        doc = {'id': 'd', 'title': 't', 'content': 'c', 'source': 's', 'updated_at': '2026',
               'reviewed': True, 'demo': False, 'population': 'all'}
        class Retriever:
            def search(self, query, budget):
                return [doc | {'content': 'different'}]
        with self.assertRaises(ServiceFailure):
            apply_retrieval({'queries': ['q']}, [doc], Retriever(), Budget(Settings()), set())
        with self.assertRaises(ServiceFailure):
            apply_retrieval({'issues': [{'kind': 'patient_fact_missing', 'status': 'open'}]},
                            [], Retriever(), Budget(Settings()), set())

    def test_integration_rejects_forged_report(self):
        with self.assertRaises(ModelOutputError):
            validate_integration({'claims': [{}], 'integration_decisions': [{'claim_index': 0,
                'reason': 'r', 'supporting_report_ids': ['forged'], 'opposing_report_ids': [],
                'evidence_ids': []}]}, [], [])

    def test_paired_metrics_negative_and_zero(self):
        def row(correct):
            return {'case_id': '1', 'repeat': 0, 'correct': correct,
                    'result': {'status': 'completed', 'metrics': {'total_tokens': 0, 'elapsed_ms': 1}}}
        result = compare([row(True)], [row(False)], samples=100)
        self.assertEqual(result['accuracy']['relative_improvement_percent'], -100)
        self.assertIsNone(result['mean_tokens']['relative_improvement_percent'])
        with self.assertRaises(ValueError):
            compare([row(True)], [])

    def test_all_optimized_routes_keep_final_verification(self):
        for marker in ('', '[demo:moderate]', '[demo:high]'):
            model = Model()
            result = MedRoute(replace(Settings(backend='demo'), collab_policy='selective',
                evidence_policy='gap_driven', integration_policy='evidence_first'), model=model).run({'message': 'demo '+marker})
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(model.calls[-1][0], 'verify')


if __name__ == '__main__':
    unittest.main()
