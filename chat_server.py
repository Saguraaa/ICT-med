"""Small team-test gateway. Runtime credentials stay on this server."""
import argparse
import json
import os
import secrets
import socket
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from config import load_env


def make_handler(runtime_url, runtime_key, access_code):
    page = (Path(__file__).parent / 'web' / 'index.html').read_bytes()
    page = page.replace(b'__ACCESS_REQUIRED__', b'true' if access_code else b'false')
    slots = threading.BoundedSemaphore(4)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, data, content_type='application/json; charset=utf-8'):
            if not isinstance(data, bytes):
                data = json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == '/':
                return self.reply(200, page, 'text/html; charset=utf-8')
            self.reply(404, {'error': 'not_found'})

        def do_POST(self):
            self.connection.settimeout(15)
            if self.path != '/api/chat':
                return self.reply(404, {'error': 'not_found'})
            if access_code and not secrets.compare_digest(self.headers.get('Authorization', '').encode(),
                                          ('Bearer ' + access_code).encode()):
                return self.reply(401, {'error': '测试口令错误，请联系项目负责人。'})
            if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
                return self.reply(415, {'error': '需要 JSON 请求。'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 65536:
                    return self.reply(413, {'error': '请求过长。'})
                body = json.loads(self.rfile.read(length))
                session = body.get('session_id', '')
                message = body.get('message')
                state = body.get('case_state', {})
                if (not isinstance(session, str) or not 1 <= len(session) <= 64
                        or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in session)
                        or not isinstance(message, str) or not 1 <= len(message.strip()) <= 4000
                        or not isinstance(state, dict)):
                    raise ValueError()
            except (ValueError, AttributeError, OSError):
                return self.reply(400, {'error': '请求格式不正确。'})
            if not slots.acquire(blocking=False):
                return self.reply(429, {'error': '当前测试人数较多，请稍后重试。'})
            try:
                payload = json.dumps({'message': message, 'case_state': state}).encode('utf-8')
                request = Request(runtime_url, data=payload, headers={
                    'Authorization': 'Bearer ' + runtime_key,
                    'Content-Type': 'application/json',
                    'x-hw-agentarts-session-id': session,
                }, method='POST')
                with urlopen(request, timeout=120) as response:
                    raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise ValueError()
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ValueError()
                self.reply(200, result)
            except HTTPError as exc:
                status = exc.code
                exc.close()
                hint = {401: '请核对运行时入站 API Key，修改后重启网页服务。',
                        403: '请检查运行时访问权限。',
                        404: '请核对运行时调用地址。',
                        429: '调用频率受限，请稍后重试。'}.get(status, '请检查 AgentArts 运行时状态。')
                self.reply(502, {'error': f'AgentArts 返回 HTTP {status}。{hint}',
                                 'error_code': 'upstream_http_error', 'upstream_status': status})
            except (URLError, OSError) as exc:
                reason = exc.reason if isinstance(exc, URLError) else exc
                if isinstance(reason, (TimeoutError, socket.timeout)):
                    code, hint = 'upstream_timeout', '等待 AgentArts 响应超时，请稍后重试。'
                elif isinstance(reason, ssl.SSLError):
                    code, hint = 'upstream_tls_error', 'HTTPS 证书验证失败，请检查本机证书或网络代理。'
                elif isinstance(reason, socket.gaierror):
                    code, hint = 'upstream_dns_error', '无法解析 AgentArts 域名，请检查网络和 DNS。'
                else:
                    code, hint = 'upstream_connection_error', '无法连接 AgentArts，请检查网络或代理设置。'
                self.reply(502, {'error': hint, 'error_code': code})
            except ValueError:
                self.reply(502, {'error': 'AgentArts 未返回预期的 JSON 对象，请检查调用地址及运行时响应。',
                                 'error_code': 'invalid_upstream_response'})
            finally:
                slots.release()

    return Handler


if __name__ == '__main__':
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8090)
    args = parser.parse_args()
    url = os.getenv('AGENTARTS_RUNTIME_URL', '')
    key = os.getenv('AGENTARTS_RUNTIME_KEY', '')
    code = os.getenv('CHAT_ACCESS_CODE', '')
    if urlsplit(url).scheme != 'https' or not urlsplit(url).netloc or not key:
        raise SystemExit('请配置 HTTPS 的 AGENTARTS_RUNTIME_URL 和 AGENTARTS_RUNTIME_KEY。')
    if code and len(code) < 12:
        raise SystemExit('CHAT_ACCESS_CODE 可留空；如设置，至少需要 12 位。')
    if args.host == '0.0.0.0':
        print(f'本机访问：http://localhost:{args.port}', flush=True)
        print(f'团队访问：http://你的电脑内网IPv4:{args.port}（用 ipconfig 查看）', flush=True)
    else:
        print(f'MedRoute chat: http://{args.host}:{args.port}', flush=True)
    ThreadingHTTPServer((args.host, args.port), make_handler(url, key, code)).serve_forever()
