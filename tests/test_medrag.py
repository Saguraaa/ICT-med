import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from agents import Budget, ModelOutputError, ServiceFailure
from config import Settings
from medrag_store import build_index, search_index
from retrieval import Retriever


class MedRAGTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        file = self.root/'source.jsonl'
        file.write_text(json.dumps({'id': 'cough1', 'title': 'Respiratory',
            'content': 'Cough and fever require assessment of respiratory symptoms.'}), encoding='utf-8')
        self.index = self.root/'index.sqlite'
        build_index([file], self.index, 'test-revision')
        self.settings = Settings(backend='openai', retrieval_backend='medrag_sqlite',
            medrag_index_path=self.index, evidence_scope='research')

    def tearDown(self):
        self.directory.cleanup()

    def test_real_fts_and_source_metadata(self):
        docs = search_index(self.index, 'cough fever', 1)
        self.assertEqual(docs[0]['id'], 'medrag:cough1')
        self.assertFalse(docs[0]['reviewed'])
        self.assertIn('/test-revision/chunk/source.jsonl', docs[0]['source'])
        self.assertTrue(docs[0]['content_hash'])

    def test_reviewed_default_filters_research_corpus(self):
        cfg = replace(self.settings, evidence_scope='reviewed')
        self.assertEqual(Retriever(cfg).search('cough', Budget(cfg)), [])
        docs = Retriever(self.settings).search('cough', Budget(self.settings))
        self.assertFalse(docs[0]['reviewed'])

    def test_chinese_query_uses_translation(self):
        with patch('retrieval.ModelClient.complete', return_value={'query': 'cough fever'}) as model:
            docs = Retriever(self.settings).search('咳嗽发热', Budget(self.settings))
        self.assertEqual(model.call_args.args[0], 'retrieval_query')
        self.assertEqual(docs[0]['id'], 'medrag:cough1')

    def test_invalid_translation_and_missing_index_fail_closed(self):
        with patch('retrieval.ModelClient.complete', return_value={'query': '咳嗽'}):
            with self.assertRaises(ModelOutputError):
                Retriever(self.settings).search('咳嗽', Budget(self.settings))
        with self.assertRaises(ServiceFailure):
            search_index(self.root/'missing.sqlite', 'cough')

    def test_index_never_overwrites_existing_file(self):
        with self.assertRaises(ValueError):
            build_index([], self.index)

    def test_research_never_releases_live_clinical_output(self):
        from medroute import MedRoute
        from test_optimization import Model
        docs = search_index(self.index, 'cough', 1)
        class FixedRetrieval:
            def search(self, query, budget):
                return docs
        cfg = replace(self.settings, enable_triage_output=True)
        with patch('medroute.rules_ready', return_value=True):
            result = MedRoute(cfg, model=Model(), retriever=FixedRetrieval()).run({'message': 'cough'})
        self.assertEqual(result['status'], 'handoff')
        self.assertEqual(result['handoff']['reason'], 'clinical_release_disabled_or_rules_unreviewed')
        self.assertTrue(result['reports'])
        self.assertFalse(result['retrieved_evidence'][0]['reviewed'])
