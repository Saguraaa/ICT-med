import io
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from chat_server import make_handler


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(
            'https://runtime.example/invocations', 'private-runtime-key', 'team-test-code'))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, code='team-test-code', state=None):
        return Request(self.url + '/api/chat', data=json.dumps({
            'message': '合成病例', 'session_id': 'member-001',
            'case_state': state or {}}).encode(), headers={
                'Authorization': 'Bearer ' + code, 'Content-Type': 'application/json'})

    def test_page_does_not_expose_runtime_key(self):
        with urlopen(self.url) as response:
            page = response.read().decode()
        self.assertIn('医路智分', page)
        self.assertNotIn('private-runtime-key', page)
        self.assertIn('const accessRequired=true;', page)

    def test_blank_code_allows_requests_without_authorization(self):
        self.server.RequestHandlerClass = make_handler(
            'https://runtime.example/invocations', 'private-runtime-key', '')
        with urlopen(self.url) as response:
            self.assertIn('const accessRequired=false;', response.read().decode())
        request = self.request()
        request.remove_header('Authorization')
        with patch('chat_server.urlopen') as upstream:
            upstream.return_value.__enter__.return_value = io.BytesIO(b'{"status":"completed"}')
            with urlopen(request) as response:
                self.assertEqual(json.load(response)['status'], 'completed')

    def test_wrong_code_never_calls_runtime(self):
        with patch('chat_server.urlopen') as upstream:
            with self.assertRaises(HTTPError) as error:
                urlopen(self.request('wrong'))
            self.assertEqual(error.exception.code, 401)
            error.exception.close()
            upstream.assert_not_called()

    def test_proxy_preserves_state_and_uses_server_credentials(self):
        state = {'user_messages': ['之前的消息']}
        result = {'response': '请补充信息', 'case_state': state}
        with patch('chat_server.urlopen') as upstream:
            upstream.return_value.__enter__.return_value = io.BytesIO(json.dumps(result).encode())
            with urlopen(self.request(state=state)) as response:
                self.assertEqual(json.load(response), result)
            forwarded = upstream.call_args.args[0]
            self.assertEqual(json.loads(forwarded.data)['case_state'], state)
            self.assertEqual(forwarded.get_header('Authorization'), 'Bearer private-runtime-key')
            self.assertEqual(forwarded.get_header('X-hw-agentarts-session-id'), 'member-001')

    def test_upstream_timeout_is_identified(self):
        with patch('chat_server.urlopen', side_effect=TimeoutError()):
            with self.assertRaises(HTTPError) as error:
                urlopen(self.request())
            with error.exception as response:
                self.assertEqual(json.load(response)['error_code'], 'upstream_timeout')

    def test_invalid_upstream_json_is_identified(self):
        with patch('chat_server.urlopen') as upstream:
            upstream.return_value.__enter__.return_value = io.BytesIO(b'not json')
            with self.assertRaises(HTTPError) as error:
                urlopen(self.request())
            with error.exception as response:
                self.assertEqual(json.load(response)['error_code'], 'invalid_upstream_response')


if __name__ == '__main__':
    unittest.main()
