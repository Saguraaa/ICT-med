"""Reproducible, interleaved ablations; live runs require explicit --live."""
import argparse
import hashlib
import json
import random
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from config import ROOT, Settings
from medroute import MedRoute
from metrics import summarize, compare
from reporting import render_report


VARIANTS = {
    'B0': {}, 'S': {'routing_strategy': 'single'}, 'F': {'routing_strategy': 'fixed_multi'},
    'A-context': {'collab_policy': 'context'}, 'A': {'collab_policy': 'selective'},
    'B': {'evidence_policy': 'gap_driven'}, 'C': {'integration_policy': 'evidence_first'},
}
for name in ('AB', 'AC', 'BC', 'ABC'):
    VARIANTS[name] = {key: value for letter in name for key, value in VARIANTS[letter].items()}


def run_suite(cases, variants, settings, output_dir, repeats=3):
    ids = [c['id'] for c in cases]
    if (len(ids) != len(set(ids)) or not ids or repeats < 1 or not variants
            or len(variants) != len(set(variants)) or any(v not in VARIANTS for v in variants)):
        raise ValueError('unique nonempty case IDs and positive repeats required')
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(ROOT.glob('*.py'))}
    manifest = {'created_at': datetime.now(timezone.utc).isoformat(), 'source_hashes': hashes,
        'case_hash': hashlib.sha256(json.dumps(cases, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        'model': settings.model, 'backend': settings.backend, 'repeats': repeats,
        'variants': {v: VARIANTS[v] for v in variants}, 'max_calls': settings.max_calls,
        'deadline_seconds': settings.deadline_seconds,
        'retrieval_backend': settings.retrieval_backend, 'evidence_scope': settings.evidence_scope,
        'clinical_acceptance': 'insufficient_evidence'}
    knowledge = settings.medrag_index_path if settings.retrieval_backend == 'medrag_sqlite' else settings.knowledge_path
    for key, path in [('knowledge_hash', knowledge), ('rules_hash', settings.rules_path)]:
        manifest[key] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    (output_dir/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    jobs = [(case, variant, repeat) for repeat in range(repeats) for case in cases for variant in variants]
    random.Random(42).shuffle(jobs)
    records = []
    with (output_dir/'results.jsonl').open('w', encoding='utf-8') as f:
        for case, variant, repeat in jobs:
            baseline = replace(settings, collab_policy='baseline', evidence_policy='baseline',
                               integration_policy='baseline', routing_strategy='adaptive')
            cfg = replace(baseline, **VARIANTS[variant])
            started = time.monotonic()
            try:
                result = MedRoute(cfg).run({'message': case['message'], 'case_state': case.get('case_state', {})})
            except Exception as exc:
                result = {'status': 'error', 'error_type': type(exc).__name__, 'metrics': {
                    'model_calls': None, 'total_tokens': None,
                    'elapsed_ms': round((time.monotonic()-started)*1000)}}
            # Only externally reviewed explicit action labels may score clinical correctness.
            allowed = case.get('allowed_actions') if case.get('reviewed') is True and settings.backend != 'demo' else None
            action = result.get('care_level') if result.get('status') == 'completed' else result.get('route')
            correct = (action in allowed and result.get('status') != 'error') if allowed else None
            record = {'case_id': case['id'], 'variant': variant, 'repeat': repeat,
                      'correct': correct, 'result': result}
            records.append(record)
            f.write(json.dumps(record, ensure_ascii=False)+'\n'); f.flush()
    groups = {v: [r for r in records if r['variant'] == v] for v in variants}
    summaries = {v: summarize(rows) for v, rows in groups.items()}
    comparisons = {v+'_vs_B0': compare(groups['B0'], groups[v]) for v in variants if v != 'B0'} if 'B0' in groups else {}
    if 'ABC' in groups:
        for v in ('AB', 'AC', 'BC'):
            if v in groups:
                comparisons['ABC_vs_'+v] = compare(groups[v], groups['ABC'])
    render_report(output_dir, manifest, summaries, comparisons)
    return summaries


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default='data/demo_cases.jsonl')
    parser.add_argument('--output', required=True)
    parser.add_argument('--variants', default=','.join(VARIANTS))
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    settings = Settings.from_env() if args.live else Settings(backend='demo')
    rows = [json.loads(line) for line in Path(args.input).read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    run_suite(rows, args.variants.split(','), settings, args.output, args.repeats)
