"""Conservative, deterministic selective communication (not trained AgentDropout)."""
from agents import ModelOutputError


def latest_reports(reports):
    latest = {}
    for report in reports:
        latest[report['role']] = report
    return list(latest.values())


def validate_action(value, roles, evidence_ids):
    if not isinstance(value, dict) or value.get('action') not in (
            'stop', 'retrieve', 'reconsult', 'clarify', 'handoff'):
        raise ModelOutputError('invalid_review_action')
    for key, limit in (('queries', 2), ('questions', 2), ('selected_roles', 4)):
        items = value.get(key, [])
        if not isinstance(items, list) or len(items) > limit or any(
                not isinstance(x, str) or not x.strip() or len(x) > 1200 for x in items):
            raise ModelOutputError('invalid_action_' + key)
    if any(role not in roles for role in value.get('selected_roles', [])):
        raise ModelOutputError('invalid_selected_role')
    issues = value.get('issues', [])
    if not isinstance(issues, list) or len(issues) > 8:
        raise ModelOutputError('invalid_issues')
    ids = set()
    for issue in issues:
        if (not isinstance(issue, dict) or not isinstance(issue.get('id'), str)
                or not issue['id'] or issue['id'] in ids
                or issue.get('kind') not in ('patient_fact_missing', 'knowledge_gap', 'interpretation_conflict')
                or issue.get('status') not in ('open', 'resolved')
                or not isinstance(issue.get('text'), str) or not issue['text'].strip()):
            raise ModelOutputError('invalid_issue')
        ids.add(issue['id'])
        for key, allowed in (('affected_roles', roles), ('evidence_ids', evidence_ids)):
            items = issue.get(key, [])
            if not isinstance(items, list) or any(x not in allowed for x in items):
                raise ModelOutputError('invalid_issue_reference')
    if value['action'] == 'stop' and any(i['status'] == 'open' for i in issues):
        raise ModelOutputError('stop_with_open_issues')
    if value['action'] == 'retrieve' and (not value.get('queries') or any(
            i['kind'] == 'patient_fact_missing' and i['status'] == 'open' for i in issues)):
        raise ModelOutputError('invalid_retrieval_action')
    if value['action'] == 'clarify' and not value.get('questions'):
        raise ModelOutputError('clarification_without_question')
    return value


def select_roles(issues, reports, allowed_roles):
    needed = {role for issue in issues if issue['status'] == 'open'
              for role in issue.get('affected_roles', [])}
    needed.update(r['role'] for r in latest_reports(reports) if r.get('uncertainties'))
    return [r for r in allowed_roles if r in needed]


def build_context(role, reports, issues):
    relevant = {r for issue in issues if issue['status'] == 'open'
                and role in issue.get('affected_roles', []) for r in issue.get('affected_roles', [])}
    relevant.add(role)
    return [r for r in latest_reports(reports) if r['role'] in relevant or r.get('needs_escalation')]
