"""Shared boundary for local HTTP and the real AgentArts adapter."""
import logging

from medroute import InputError, MedRoute

logger = logging.getLogger('medroute')


def handle_payload(payload, session_id=None, service=None):
    try:
        return (service or MedRoute()).run(payload, session_id=session_id)
    except InputError as exc:
        return {'status': 'error', 'error': 'invalid_input', 'response': str(exc)}
    except Exception as exc:
        # Logs intentionally omit request bodies, model responses and exception messages.
        logger.error('Unhandled request error: %s', type(exc).__name__)
        return {'status': 'error', 'error': 'internal_error',
                'response': '服务暂时无法处理请求，请联系医务人员；当前未完成自动转接。'}
