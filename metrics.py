"""Paired case-level metrics. Missing usage/labels never become zero."""
import random
import statistics


def summarize(records):
    n = len(records)
    correct = [r.get('correct') for r in records]
    tokens = [r['result'].get('metrics', {}).get('total_tokens') for r in records]
    calls = [r['result'].get('metrics', {}).get('model_calls') for r in records]
    return {'attempts': n, 'labelled': sum(x is not None for x in correct),
            'correct': sum(x is True for x in correct),
            'accuracy': sum(x is True for x in correct)/n if n and all(x is not None for x in correct) else None,
            'coverage': sum(r['result'].get('status') == 'completed' for r in records)/n if n else None,
            'mean_tokens': sum(tokens)/n if n and all(x is not None for x in tokens) else None,
            'model_calls': sum(calls) if all(x is not None for x in calls) else None,
            'p50_ms': statistics.median([r['result']['metrics']['elapsed_ms'] for r in records]) if n else None}


def compare(base, candidate, samples=10000):
    def grouped(rows):
        result = {}
        for row in rows:
            key = (row['case_id'], row['repeat'])
            if key in result:
                raise ValueError('duplicate_case_repeat')
            result[key] = row
        return result
    left, right = grouped(base), grouped(candidate)
    if left.keys() != right.keys():
        raise ValueError('unpaired_results')
    keys = sorted(left)
    b, o = summarize(base), summarize(candidate)
    result = {}
    for metric, lower in (('accuracy', False), ('coverage', False), ('mean_tokens', True), ('p50_ms', True)):
        x, y = b[metric], o[metric]
        sign = -1 if lower else 1
        result[metric] = {'baseline': x, 'candidate': y,
            'difference': y-x if x is not None and y is not None else None,
            'relative_improvement_percent': sign*(y-x)/x*100 if x not in (None, 0) and y is not None else None,
            'difference_ci95': None}
    # Resample patients, retaining all repetitions within each patient.
    cases = sorted({k[0] for k in keys})
    rng = random.Random(42)
    if cases and b['accuracy'] is not None and o['accuracy'] is not None:
        diffs = []
        for _ in range(samples):
            selected = [rng.choice(cases) for _ in cases]
            delta = [int(right[k]['correct'])-int(left[k]['correct'])
                     for case in selected for k in keys if k[0] == case]
            diffs.append(statistics.mean(delta))
        diffs.sort()
        result['accuracy']['difference_ci95'] = [diffs[int(samples*.025)], diffs[min(samples-1,int(samples*.975))]]
    return result
