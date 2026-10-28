"""Deterministic gates; shipped rules only exercise software, not clinical triage."""
import json

from agents import ModelOutputError, ServiceFailure


def read_rules(path):
    try:
        config = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(config, dict) or not isinstance(config.get('rules'), list):
            raise ValueError()
        for rule in config['rules']:
            if not isinstance(rule, dict) or not isinstance(rule.get('id'), str):
                raise ValueError()
            if not isinstance(rule.get('patterns'), list) or not rule['patterns']:
                raise ValueError()
            if any(not isinstance(p, str) or not p for p in rule['patterns']):
                raise ValueError()
        return config
    except (ValueError, TypeError, OSError):
        raise ServiceFailure('invalid_rules_file') from None


def screen(text, config, demo):
    # Conservative literal matching, no claim of clinical negation/temporality detection.
    return [r['id'] for r in config['rules']
            if (demo or (r.get('reviewed') is True and not r.get('demo', False)))
            and any(p.casefold() in text.casefold() for p in r['patterns'])]


def rules_ready(config):
    rules = config['rules']
    return bool(rules) and config.get('reviewed') is True and all(
        r.get('reviewed') is True and not r.get('demo', False) and r.get('source') for r in rules)


def strings(value, max_items=8, max_length=1200):
    return (isinstance(value, list) and len(value) <= max_items
            and all(isinstance(item, str) and 0 < len(item) <= max_length for item in value))


def validate_expert(obj):
    if (not isinstance(obj.get('summary'), str) or not obj['summary'].strip()
            or len(obj['summary']) > 6000 or not strings(obj.get('evidence_ids'))
            or type(obj.get('needs_escalation')) is not bool
            or not strings(obj.get('uncertainties'))):
        raise ModelOutputError('invalid_expert_report')
    return obj


def validate_review(obj, verification=False):
    key = 'supported' if verification else 'stop'
    if type(obj.get(key)) is not bool or type(obj.get('needs_escalation')) is not bool:
        raise ModelOutputError('invalid_review')
    if verification:
        if not strings(obj.get('issues')):
            raise ModelOutputError('invalid_verification_issues')
    elif not isinstance(obj.get('feedback'), str) or len(obj['feedback']) > 4000:
        raise ModelOutputError('invalid_moderator_feedback')
    return obj


def check_claims(candidate, documents):
    if (not isinstance(candidate.get('response'), str) or not candidate['response'].strip()
            or len(candidate['response']) > 10000
            or candidate.get('care_level') not in ('routine', 'prompt', 'emergency', 'human')
            or not strings(candidate.get('uncertainties'))):
        raise ModelOutputError('invalid_final_response')
    claims = candidate.get('claims')
    if not isinstance(claims, list) or not 1 <= len(claims) <= 12:
        return ['missing_claims']
    available = {doc['id'] for doc in documents}
    issues = []
    for claim in claims:
        if not isinstance(claim, dict) or not isinstance(claim.get('text'), str) or not claim['text'].strip():
            issues.append('invalid_claim')
            continue
        ids = claim.get('evidence_ids')
        if not strings(ids) or not ids:
            issues.append('claim_without_evidence')
        elif any(eid not in available for eid in ids):
            issues.append('unknown_evidence_id')
    return sorted(set(issues))
