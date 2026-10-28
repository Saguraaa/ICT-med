"""Run offline cases, or a prepared dataset. No medical accuracy claims from demo cases."""
import argparse
import json
from dataclasses import replace
from pathlib import Path

from config import Settings
from medroute import MedRoute


def evaluate(input_path, output_path, service):
    rows = [json.loads(line) for line in Path(input_path).read_text(encoding='utf-8-sig').splitlines()
            if line.strip()]
    results = []
    for row in rows:
        result = service.run({'message': row['message'], 'case_state': row.get('case_state', {})})
        results.append({'id': row['id'], 'expected_route': row.get('expected_route'),
                        'matched': result['route'] == row.get('expected_route'), 'result': result})
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    labelled = [r for r in results if r['expected_route'] is not None]
    summary = {'cases': len(results), 'labelled': len(labelled),
               'routing_matches': sum(r['matched'] for r in labelled),
               'model_calls': sum(r['result']['metrics']['model_calls'] for r in results)}
    print(json.dumps(summary, ensure_ascii=False))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default='data/demo_cases.jsonl')
    parser.add_argument('--output', default='work/evaluation.json')
    parser.add_argument('--strategy', choices=['adaptive', 'single', 'fixed_multi'], default='adaptive')
    args = parser.parse_args()
    evaluate(args.input, args.output, MedRoute(replace(Settings.from_env(), routing_strategy=args.strategy)))
