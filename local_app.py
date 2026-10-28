"""Dependency-free local server; cloud deployments use app.py instead."""
import argparse
import json
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from config import Settings
from medroute import MedRoute
from service import handle_payload


def make_handler(settings, service=None):
    service = service or MedRoute(settings)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Do not log bodies or credentials.

        def send_json(self, code, body):
            data = json.dumps(body, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == '/ping':
                self.send_json(200, {'status': 'Healthy', 'mode': settings.backend,
                                     'clinical_output_enabled': settings.enable_triage_output})
            else:
                self.send_json(404, {'error': 'not_found'})

        def do_POST(self):
            self.connection.settimeout(10)
            if self.path != '/invocations':
                return self.send_json(404, {'error': 'not_found'})
            if settings.api_token and not secrets.compare_digest(
                    self.headers.get('Authorization', ''), 'Bearer ' + settings.api_token):
                return self.send_json(401, {'error': 'unauthorized'})
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                return self.send_json(415, {'error': 'expected_application_json'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 65536:
                    return self.send_json(413, {'error': 'invalid_body_size'})
                payload = json.loads(self.rfile.read(length))
            except (ValueError, OSError):
                return self.send_json(400, {'error': 'invalid_json'})
            result = handle_payload(payload, service=service)
            code = 400 if result.get('error') == 'invalid_input' else (
                500 if result.get('error') == 'internal_error' else 200)
            self.send_json(code, result)

    return Handler


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=int(os.getenv('AGENT_RUN_PORT', '8080')))
    args = parser.parse_args()
    settings = Settings.from_env()
    print(f'MedRoute local server: http://{args.host}:{args.port} mode={settings.backend}', flush=True)
    ThreadingHTTPServer((args.host, args.port), make_handler(settings)).serve_forever()
