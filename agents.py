"""JSON model calls, request-local budgets and an explicit offline fixture backend."""
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse

from prompts import system_prompt


class ServiceFailure(Exception):
    pass


class BudgetExceeded(ServiceFailure):
    pass


class ModelOutputError(ServiceFailure):
    def __init__(self, code, details=None):
        super().__init__(code)
        self.details = details or {}


class Budget:
    def __init__(self, settings):
        self.started = time.monotonic()
        self.deadline = self.started + settings.deadline_seconds
        self.max_calls = settings.max_calls
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.trace = []

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise BudgetExceeded('request_deadline')
        return remaining

    def before_call(self, task):
        self.remaining()
        if self.calls >= self.max_calls:
            raise BudgetExceeded('model_call_limit')
        self.calls += 1
        self.trace.append({'event': 'model_call', 'task': task})

    def metrics(self):
        return {'model_calls': self.calls, 'input_tokens': self.input_tokens,
                'output_tokens': self.output_tokens,
                'elapsed_ms': round((time.monotonic() - self.started) * 1000)}


def post_json(url, data, timeout, api_key='', max_bytes=2_000_000):
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = 'Bearer ' + api_key
    req = Request(url, json.dumps(data, ensure_ascii=False).encode(), headers, method='POST')
    try:
        with urlopen(req, timeout=timeout) as response:
            raw = response.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ServiceFailure('upstream_response_too_large')
        return json.loads(raw)
    except HTTPError as exc:
        # Do not return upstream bodies, credentials or patient text in error messages.
        raise ServiceFailure(f'upstream_http_{exc.code}') from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise ServiceFailure('upstream_unavailable_or_invalid_json') from None


def parse_object(content):
    if not isinstance(content, str):
        raise ModelOutputError('model_content_not_text')
    text = content.strip()
    if text.startswith('```') and text.endswith('```'):
        text = text.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    try:
        obj = json.loads(text)
    except ValueError:
        raise ModelOutputError('model_invalid_json') from None
    if not isinstance(obj, dict):
        raise ModelOutputError('model_json_not_object')
    return obj


class ModelClient:
    def __init__(self, settings):
        self.settings = settings

    def complete(self, task, payload, budget):
        budget.before_call(task)
        cfg = self.settings
        if cfg.backend == 'demo':
            return demo_response(task, payload)
        if not cfg.api_key or not cfg.model:
            raise ServiceFailure('model_not_configured')
        request = {
            'model': cfg.model,
            'messages': [
                {'role': 'system', 'content': system_prompt(task)},
                {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
            ],
            'temperature': 0,
        }
        json_mode = cfg.json_mode == 'true' or (
            cfg.json_mode == 'auto' and urlparse(cfg.model_url).hostname == 'api.deepseek.com')
        if json_mode:
            request['response_format'] = {'type': 'json_object'}
        result = post_json(cfg.model_url + '/chat/completions', request,
                           min(cfg.request_timeout, budget.remaining()), cfg.api_key)
        if not isinstance(result, dict):
            raise ModelOutputError('model_invalid_response')
        try:
            usage = result.get('usage') or {}
            budget.input_tokens += int(usage.get('prompt_tokens') or 0)
            budget.output_tokens += int(usage.get('completion_tokens') or 0)
            content = result['choices'][0]['message']['content']
        except (KeyError, TypeError, ValueError, IndexError):
            raise ModelOutputError('model_invalid_response') from None
        budget.remaining()
        return parse_object(content)


def demo_response(task, payload):
    """Synthetic markers exercise software paths; no medical inference is performed."""
    text = '\n'.join(payload.get('messages', []))
    if task == 'triage':
        return {
            'risk': 'urgent' if '[demo:urgent]' in text else 'routine',
            'complexity': 'high' if '[demo:high]' in text else (
                'moderate' if '[demo:moderate]' in text else 'low'),
            'needs_clarification': '[demo:clarify]' in text and '[demo:complete]' not in text,
            'questions': ['【离线演示】请补充 [demo:complete]，以验证下一轮流程。'],
            'specialties': ['general', 'respiratory', 'digestive'],
            'summary': '合成软件测试输入，不代表医学评估。', 'reason': '显式演示标记路由',
        }
    if task == 'expert':
        return {'summary': f"【离线演示】{payload['role']} 已读取当前病例与前序报告。",
                'evidence_ids': [d['id'] for d in payload['evidence'][:1]],
                'needs_escalation': False, 'uncertainties': []}
    if task == 'moderator':
        return {'stop': True, 'needs_escalation': False, 'feedback': '合成演示达到停止条件'}
    if task == 'final':
        ids = [d['id'] for d in payload['evidence'][:1]]
        return {'response': '【离线演示】已完成所选协作流程。本结果仅验证软件，不构成健康建议。',
                'care_level': 'routine',
                'claims': [{'text': '该输出仅供流程测试。', 'evidence_ids': ids}],
                'uncertainties': []}
    if task == 'verify':
        return {'supported': True, 'needs_escalation': False, 'issues': []}
    raise ValueError('Unknown demo task')
