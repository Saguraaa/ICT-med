"""Bounded supplemental retrieval; never replace patient facts with literature."""
import hashlib
import json
import time
from agents import ServiceFailure
from retrieval import clean_document


def fingerprint(doc):
    return hashlib.sha256(json.dumps({k: doc.get(k) for k in (
        'title', 'content', 'source', 'updated_at', 'population')},
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def apply_retrieval(action, evidence, retriever, budget, seen_queries, demo=False,
                    max_queries=2, max_documents=8, research=False):
    if any(i['kind'] == 'patient_fact_missing' and i['status'] == 'open'
           for i in action.get('issues', [])):
        raise ServiceFailure('patient_facts_require_clarification')
    merged = {d['id']: d for d in evidence}
    for query in action.get('queries', [])[:max_queries]:
        normalized = ' '.join(query.casefold().split())
        if normalized in seen_queries:
            continue
        seen_queries.add(normalized)
        budget.remaining()
        started = time.monotonic()
        docs = retriever.search(query, budget)
        added = []
        for raw in docs:
            doc = clean_document(raw, demo, research)
            if doc is None:
                continue
            if doc['id'] in merged:
                if fingerprint(doc) != fingerprint(merged[doc['id']]):
                    raise ServiceFailure('evidence_version_conflict')
                continue
            if len(merged) >= max_documents:
                raise ServiceFailure('evidence_capacity_exceeded')
            merged[doc['id']] = doc | {'content_hash': fingerprint(doc)}
            added.append(doc['id'])
        budget.trace.append({'event': 'supplemental_retrieval', 'query': query,
                             'issue_ids': [i['id'] for i in action.get('issues', [])],
                             'added_ids': added, 'elapsed_ms': round((time.monotonic()-started)*1000)})
    return list(merged.values())
