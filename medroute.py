"""Adaptive collaboration inspired by MDAgents, with explicit MedRoute extensions."""
import uuid

from agents import Budget, ModelClient, ModelOutputError, ServiceFailure
from config import Settings
from prompts import SPECIALTIES
from retrieval import Retriever
from safety import (check_claims, read_rules, rules_ready, screen, strings,
                    validate_expert, validate_review)


class InputError(ValueError):
    pass


def validate_input(payload):
    if not isinstance(payload, dict):
        raise InputError('请求体必须是 JSON 对象。')
    message = payload.get('message')
    if not isinstance(message, str) or not message.strip() or len(message) > 4000:
        raise InputError('message 必须是 1~4000 字符的文本。')
    state = payload.get('case_state', {})
    if not isinstance(state, dict):
        raise InputError('case_state 必须是对象。')
    history = state.get('user_messages', [])
    if not strings(history, max_items=11, max_length=4000):
        raise InputError('会话最多保留 11 条历史用户消息；请开始新会话或交给人工。')
    messages = history + [message.strip()]
    if sum(map(len, messages)) > 16000:
        raise InputError('病例总文本超过 16000 字符，请交给人工继续处理。')
    # Only original user text is carried forward; supplied prior decisions/risks are ignored.
    return messages


def validate_triage(obj):
    errors = {}
    if obj.get('risk') not in ('routine', 'urgent', 'unknown'):
        errors['risk'] = 'required: routine, urgent or unknown'
    if obj.get('complexity') not in ('low', 'moderate', 'high'):
        errors['complexity'] = 'required: low, moderate or high'
    if type(obj.get('needs_clarification')) is not bool:
        errors['needs_clarification'] = 'required: JSON boolean'
    if not strings(obj.get('questions'), max_items=2):
        errors['questions'] = 'required: string array, at most 2 items; use [] instead of null'
    if (not strings(obj.get('specialties'), max_items=4, max_length=80)
            or any(role not in SPECIALTIES for role in obj['specialties'])):
        errors['specialties'] = 'required: array of allowed specialty identifiers'
    if (not isinstance(obj.get('summary'), str) or not obj['summary'].strip()
            or len(obj['summary']) > 6000):
        errors['summary'] = 'required: nonempty string, at most 6000 characters'
    if not isinstance(obj.get('reason'), str) or len(obj['reason']) > 2000:
        errors['reason'] = 'required: string, at most 2000 characters'
    if errors:
        # Expected types only: never include raw model values or patient text in diagnostics.
        raise ModelOutputError('invalid_triage', errors)
    if obj['needs_clarification'] and not obj['questions']:
        raise ModelOutputError('clarification_without_question', {'questions': 'required when clarifying'})
    return obj


class MedRoute:
    def __init__(self, settings=None, model=None, retriever=None):
        self.settings = settings or Settings.from_env()
        self.model = model or ModelClient(self.settings)
        self.retriever = retriever or Retriever(self.settings)

    def run(self, payload, session_id=None):
        messages = validate_input(payload)
        budget = Budget(self.settings)
        out = {
            'request_id': str(uuid.uuid4()), 'session_id': session_id,
            'mode': self.settings.backend, 'status': 'handoff', 'route': 'human',
            'response': '', 'case_state': {'user_messages': messages},
            'triage': None, 'reports': [], 'citations': [], 'retrieved_evidence': [],
            'claims': [], 'verification': None, 'handoff': None,
        }

        def finish(status, route, response, reason=None):
            out.update(status=status, route=route, response=response)
            if reason:
                out['handoff'] = {
                    'reason': reason, 'transfer_status': 'not_connected',
                    'case_summary': (out['triage'] or {}).get('summary', ''),
                    'user_messages': messages,
                    'unresolved': [u for r in out['reports'] for u in r.get('uncertainties', [])],
                }
                budget.trace.append({'event': 'handoff', 'reason': reason})
            out['trace'] = budget.trace
            out['metrics'] = budget.metrics()
            if self.settings.backend == 'demo' and not out['response'].startswith('【离线演示】'):
                out['response'] = '【离线演示，仅验证软件流程】' + out['response']
            return out

        def handoff(reason, urgent=False):
            text = ('当前描述触发了需要及时线下评估的风险信号。请立即联系当地急救或急诊服务，'
                    '不要等待本系统继续分析。' if urgent else
                    '当前信息或依据不足以支持自动分诊，请联系医务人员进一步评估。')
            text += '本系统尚未连接人工接诊服务，此提示不表示已完成转接。'
            return finish('escalated' if urgent else 'handoff',
                          'safety_escalation' if urgent else 'human', text, reason)

        try:
            rules = read_rules(self.settings.rules_path)
            matches = screen('\n'.join(messages), rules, self.settings.backend == 'demo')
            budget.trace.append({'event': 'risk_precheck', 'rule_ids': matches})
            if matches:
                return handoff('red_flag_rule', urgent=True)
            triage = validate_triage(self.model.complete('triage', {'messages': messages}, budget))
            out['triage'] = triage
            budget.trace.append({'event': 'routing', 'complexity': triage['complexity'],
                                 'risk': triage['risk']})
            if triage['risk'] == 'urgent':
                return handoff('model_urgent', urgent=True)
            if triage['risk'] == 'unknown':
                return handoff('unresolved_risk')
            if triage['needs_clarification']:
                return finish('need_more_info', 'clarification', '\n'.join(triage['questions']))

            evidence = self.retriever.search(triage['summary'] + '\n' + '\n'.join(messages), budget)
            out['retrieved_evidence'] = evidence
            if not evidence:
                return handoff('no_reviewed_evidence')
            allowed_ids = {doc['id'] for doc in evidence}

            def expert(role, stage, previous=None, feedback=''):
                report = validate_expert(self.model.complete('expert', {
                    'role': SPECIALTIES[role], 'stage': stage, 'messages': messages,
                    'case': triage, 'evidence': evidence,
                    'previous_reports': list(out['reports']),
                    'previous_opinions': previous or [], 'feedback': feedback,
                }, budget))
                if any(eid not in allowed_ids for eid in report['evidence_ids']):
                    raise ModelOutputError('expert_unknown_citation')
                report = report | {'role': role, 'stage': stage}
                out['reports'].append(report)
                budget.trace.append({'event': 'expert_report', 'role': role, 'stage': stage})
                return report

            roles = list(dict.fromkeys(triage['specialties']))[:self.settings.max_agents]
            if not roles:
                roles = ['general']
            complexity = triage['complexity']
            if self.settings.routing_strategy == 'single':
                complexity = 'low'
            elif self.settings.routing_strategy == 'fixed_multi':
                complexity, roles = 'moderate', ['general', 'respiratory', 'digestive'][:self.settings.max_agents]
            if complexity != 'low' and len(roles) < 2:
                roles.append('general' if roles[0] != 'general' else 'respiratory')
            budget.trace.append({'event': 'collaboration_plan',
                                 'strategy': self.settings.routing_strategy,
                                 'complexity': complexity,
                                 'roles': ['general'] if complexity == 'low' else roles})
            route = {'low': 'single', 'moderate': 'multi', 'high': 'multi_team'}[complexity]
            if complexity == 'low':
                report = expert('general', 'primary_care')
                if report['needs_escalation']:
                    return handoff('expert_escalation', urgent=True)
                if report['uncertainties']:
                    return handoff('unresolved_expert_uncertainty')
            else:
                if complexity == 'high':
                    report = expert('general', 'initial_assessment_team')
                    if report['needs_escalation']:
                        return handoff('initial_team_escalation', urgent=True)
                previous, feedback, stopped = [], '', False
                for round_no in range(1, self.settings.max_rounds + 1):
                    # Every participant sees the complete previous round, not a partial empty log.
                    current = []
                    for role in roles:
                        report = expert(role, f'specialist_round_{round_no}', previous, feedback)
                        current.append(report)
                        if report['needs_escalation']:
                            return handoff('specialist_escalation', urgent=True)
                    review = validate_review(self.model.complete('moderator', {
                        'case': triage, 'opinions': current, 'evidence': evidence,
                        'previous_reports': out['reports'],
                    }, budget))
                    budget.trace.append({'event': 'discussion_review', 'round': round_no,
                                         'stop': review['stop']})
                    if review['needs_escalation']:
                        return handoff('moderator_escalation', urgent=True)
                    if review['stop'] and not any(r['uncertainties'] for r in current):
                        stopped = True
                        break
                    previous, feedback = current, review['feedback']
                if not stopped:
                    return handoff('discussion_limit_unresolved')
                if complexity == 'high':
                    report = expert('general', 'final_review_team')
                    if report['needs_escalation']:
                        return handoff('final_team_escalation', urgent=True)
                    if report['uncertainties']:
                        return handoff('final_team_unresolved')

            candidate = self.model.complete('final', {
                'case': triage, 'messages': messages, 'reports': out['reports'], 'evidence': evidence,
            }, budget)
            issues = check_claims(candidate, evidence)
            if candidate.get('care_level') == 'emergency':
                return handoff('final_urgent', urgent=True)
            if candidate.get('care_level') == 'human' or candidate.get('uncertainties'):
                return handoff('final_uncertainty')
            if issues:
                out['verification'] = {'supported': False, 'issues': issues}
                return handoff('citation_integrity_failed')
            verification = validate_review(self.model.complete('verify', {
                'case': triage, 'messages': messages, 'candidate': candidate, 'evidence': evidence,
            }, budget), verification=True)
            out['verification'] = verification
            if verification['needs_escalation']:
                return handoff('verification_risk', urgent=True)
            if not verification['supported'] or verification['issues']:
                return handoff('evidence_support_failed')
            if self.settings.backend != 'demo' and (
                    not self.settings.enable_triage_output or not rules_ready(rules)):
                return handoff('clinical_release_disabled_or_rules_unreviewed')
            budget.remaining()
            ids = {eid for claim in candidate['claims'] for eid in claim['evidence_ids']}
            out['citations'] = [d for d in evidence if d['id'] in ids]
            out['claims'] = candidate['claims']
            out['care_level'] = candidate['care_level']
            return finish('completed', route, candidate['response'])
        except ServiceFailure as exc:
            if isinstance(exc, ModelOutputError) and exc.details:
                out['diagnostics'] = {'validation_errors': exc.details}
            return handoff(str(exc))


def run_medroute(payload, session_id=None):
    return MedRoute().run(payload, session_id=session_id)
