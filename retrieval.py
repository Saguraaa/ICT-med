"""Local lexical retrieval or a configured HTTP retrieval service.

This adapter is not the upstream MedRAG toolkit. The HTTP contract can bridge it.
"""
import json
import re
from collections import Counter
from math import log
from urllib.parse import urlparse

from agents import ServiceFailure, post_json


def terms(text):
    english = re.findall(r'[a-z0-9_]+', text.lower())
    chinese = re.findall(r'[\u4e00-\u9fff]+', text)
    return english + [part[i:i + 2] for part in chinese for i in range(max(1, len(part) - 1))]


def clean_document(doc, demo=False):
    if not isinstance(doc, dict):
        raise ServiceFailure('invalid_evidence_document')
    fields = ('id', 'title', 'content', 'source', 'updated_at')
    if any(not isinstance(doc.get(key), str) or not doc[key].strip() for key in fields):
        raise ServiceFailure('evidence_missing_metadata')
    if len(doc['content']) > 12000 or len(doc['id']) > 120:
        raise ServiceFailure('evidence_too_large')
    if not demo and (doc.get('reviewed') is not True or doc.get('demo') is True):
        return None
    return {key: doc[key] for key in fields} | {
        'reviewed': doc.get('reviewed') is True, 'demo': doc.get('demo') is True,
        'population': str(doc.get('population', '未指定'))[:500],
    }


class Retriever:
    def __init__(self, settings):
        self.settings = settings

    def search(self, query, budget):
        cfg = self.settings
        budget.remaining()
        if cfg.retrieval_url:
            if urlparse(cfg.retrieval_url).scheme not in ('https', 'http'):
                raise ServiceFailure('invalid_retrieval_url')
            response = post_json(cfg.retrieval_url, {'query': query, 'top_k': cfg.top_k},
                                 min(cfg.request_timeout, budget.remaining()), cfg.retrieval_key)
            if not isinstance(response, dict) or not isinstance(response.get('documents'), list):
                raise ServiceFailure('invalid_retrieval_response')
            raw_docs = response['documents'][:cfg.top_k]
        else:
            try:
                raw_docs = [json.loads(line) for line in cfg.knowledge_path.read_text(
                    encoding='utf-8-sig').splitlines() if line.strip()]
            except (OSError, ValueError):
                raise ServiceFailure('knowledge_file_unavailable') from None
        docs, ids = [], set()
        for raw in raw_docs:
            doc = clean_document(raw, demo=cfg.backend == 'demo')
            if doc is not None:
                if doc['id'] in ids:
                    raise ServiceFailure('duplicate_evidence_id')
                ids.add(doc['id'])
                docs.append(doc)
        if not cfg.retrieval_url:
            query_terms = set(terms(query))
            corpus_terms = [Counter(terms(d['title'] + ' ' + d['content'])) for d in docs]
            scored = []
            for doc, counts in zip(docs, corpus_terms):
                # Simple overlap + IDF baseline, deliberately not called BM25 or MedRAG.
                score = sum((1 + log((len(docs) + 1) / (1 + sum(t in c for c in corpus_terms))))
                            for t in query_terms if t in counts)
                if score > 0:
                    scored.append(doc | {'score': round(score, 4)})
            docs = sorted(scored, key=lambda d: d['score'], reverse=True)[:cfg.top_k]
        budget.remaining()
        budget.trace.append({'event': 'retrieval', 'document_ids': [d['id'] for d in docs]})
        return docs
