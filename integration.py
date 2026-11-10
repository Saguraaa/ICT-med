"""Check auditable evidence-first integration references, not medical truth."""
from agents import ModelOutputError


def validate_integration(candidate, reports, evidence):
    decisions = candidate.get('integration_decisions')
    claims = candidate.get('claims', [])
    if (not isinstance(claims, list) or any(not isinstance(c, dict) for c in claims)
            or not isinstance(decisions, list) or len(decisions) != len(claims)):
        raise ModelOutputError('missing_integration_decisions')
    report_ids = {r['report_id'] for r in reports}
    evidence_ids = {d['id'] for d in evidence}
    indexes = set()
    for decision in decisions:
        if not isinstance(decision, dict):
            raise ModelOutputError('invalid_integration_decision')
        index = decision.get('claim_index')
        if type(index) is not int or not 0 <= index < len(claims) or index in indexes:
            raise ModelOutputError('invalid_integration_claim_index')
        indexes.add(index)
        if not isinstance(decision.get('reason'), str) or not decision['reason'].strip():
            raise ModelOutputError('missing_integration_reason')
        for key, allowed in (('supporting_report_ids', report_ids),
                             ('opposing_report_ids', report_ids), ('evidence_ids', evidence_ids)):
            refs = decision.get(key)
            if not isinstance(refs, list) or any(not isinstance(x, str) or x not in allowed for x in refs):
                raise ModelOutputError('invalid_integration_reference')
        if not set(claims[index].get('evidence_ids', [])).issubset(decision['evidence_ids']):
            raise ModelOutputError('integration_evidence_mismatch')
    return decisions
