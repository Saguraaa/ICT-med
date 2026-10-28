"""Optional tests against the installed official SDK, never a fake replacement."""
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

from config import ROOT

SDK_AVAILABLE = importlib.util.find_spec('agentarts') is not None


@unittest.skipUnless(SDK_AVAILABLE, 'Install requirements.txt to verify the real AgentArts adapter')
class AgentArtsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env_patch = patch.dict(os.environ, {'MODEL_BACKEND': 'demo'})
        self.env_patch.start()
        import httpx
        from app import app
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test')

    async def asyncTearDown(self):
        await self.client.aclose()
        self.env_patch.stop()

    async def test_sdk_health_and_context(self):
        ping = await self.client.get('/ping')
        self.assertEqual(ping.status_code, 200)
        response = await self.client.post('/invocations', json={'message': 'demo [demo:high]'},
                                         headers={'X-Hw-Agentarts-Session-Id': 'sdk-session'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('charset=utf-8', response.headers['content-type'].lower())
        self.assertEqual(response.json()['route'], 'multi_team')
        self.assertEqual(response.json()['session_id'], 'sdk-session')
        self.assertTrue(response.content.decode('utf-8').find('【离线演示】') >= 0)

    async def test_sdk_rejects_missing_business_input(self):
        response = await self.client.post('/invocations', json={})
        self.assertEqual(response.json()['error'], 'invalid_input')


@unittest.skipUnless(SDK_AVAILABLE, 'Install requirements.txt to verify real SDK server startup')
class AgentArtsServerTests(unittest.TestCase):
    def test_sdk_starts_and_accepts_real_http(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        env = os.environ | {'MODEL_BACKEND': 'demo', 'AGENT_RUN_PORT': str(port),
                            'NO_PROXY': '127.0.0.1,localhost'}
        process = subprocess.Popen([sys.executable, 'app.py'], cwd=ROOT, env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        url = f'http://127.0.0.1:{port}'
        try:
            deadline = time.monotonic() + 25
            while True:
                try:
                    with urlopen(url + '/ping', timeout=1) as response:
                        self.assertEqual(response.status, 200)
                    break
                except OSError:
                    if process.poll() is not None or time.monotonic() > deadline:
                        self.fail('Official SDK HTTP server did not start')
                    time.sleep(0.1)
            req = Request(url + '/invocations', b'{"message":"demo [demo:moderate]"}',
                          {'Content-Type': 'application/json'}, method='POST')
            with urlopen(req, timeout=5) as response:
                self.assertEqual(response.headers.get_content_charset(), 'utf-8')
                self.assertEqual(json.load(response)['route'], 'multi')
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
