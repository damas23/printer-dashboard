"""Integration checks with a fake printer; never contact real devices."""
import concurrent.futures
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def wait_for(fn, timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if fn():
                return
        except (OSError, ValueError, KeyError, IndexError):
            pass
        time.sleep(.05)
    raise AssertionError('Timed out waiting for condition')


class FakePrinter(BaseHTTPRequestHandler):
    calls = 0

    def log_message(self, *_):
        pass

    def do_GET(self):
        type(self).calls += 1
        values = {
            '/home/api/about': {'DevFrndlName': 'Test printer', 'SerialNumber': 'TEST001'},
            '/home/api/supplies-info': {'Supplies': [{'Name': 'TONER_K', 'Remaining': 42, 'State': 'READY'}]},
        }
        body = json.dumps(values.get(self.path, {})).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class SplitIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name) / 'data'
        self.data.mkdir()
        FakePrinter.calls = 0
        self.printer = ThreadingHTTPServer(('127.0.0.1', 0), FakePrinter)
        self.thread = threading.Thread(target=self.printer.serve_forever, daemon=True)
        self.thread.start()
        cfg = Path(self.tmp.name) / 'config.json'
        cfg.write_text(json.dumps({'poll_interval_seconds': 300, 'http_timeout_seconds': 1,
                                  'printers': [{'id': 'test', 'ip': f'127.0.0.1:{self.printer.server_port}'}]}))
        self.port = free_port()
        self.env = {**os.environ, 'DATA_DIR': str(self.data), 'CONFIG_PATH': str(cfg), 'PORT': str(self.port)}
        self.processes = []
        self.start('app.py')
        wait_for(lambda: self.get('/api/health')['ok'])

    def tearDown(self):
        for p in self.processes:
            if p.poll() is None:
                p.terminate()
            try:
                p.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.communicate()
        self.printer.shutdown()
        self.printer.server_close()
        self.tmp.cleanup()

    def start(self, file):
        p = subprocess.Popen([sys.executable, file], cwd=ROOT, env=self.env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.processes.append(p)
        return p

    def get(self, path, method='GET', body=None):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', method=method,
                                     data=json.dumps(body).encode() if body is not None else None)
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.load(r)

    def test_backend_never_polls_and_does_not_serve_frontend(self):
        self.assertEqual(self.get('/api/state')['printers'], [])
        self.assertEqual(self.get('/api/collector')['health'], 'starting')
        queued = self.get('/api/collect', 'POST')
        self.assertTrue(queued['queued'])
        self.assertEqual(FakePrinter.calls, 0)
        with self.assertRaises(urllib.error.HTTPError) as err:
            self.get('/')
        self.assertEqual(err.exception.code, 404)
        with self.assertRaises(urllib.error.HTTPError) as err:
            self.get('/api/collect')
        self.assertEqual(err.exception.code, 405)

    def test_worker_collects_and_processes_queued_request(self):
        request = self.get('/api/collect', 'POST')
        self.assertEqual(request['request_id'], self.get('/api/collect', 'POST')['request_id'])
        self.start('worker.py')
        wait_for(lambda: self.get('/api/state')['printers'][0]['model'] == 'Test printer')
        wait_for(lambda: not self.get('/api/collector')['request_pending'])
        self.assertEqual(self.get('/api/state')['printers'][0]['supplies'][0]['remaining'], 42)
        self.assertEqual(self.get('/api/collector')['health'], 'healthy')
        self.assertEqual(FakePrinter.calls, 6)
        # Restart only the API: the worker and its cached state remain available.
        api = self.processes[0]
        api.terminate()
        api.wait(timeout=3)
        self.start('app.py')
        wait_for(lambda: self.get('/api/health')['ok'])
        self.assertEqual(self.get('/api/state')['printers'][0]['model'], 'Test printer')
        self.assertEqual(FakePrinter.calls, 6)
        self.get('/api/collect', 'POST')
        wait_for(lambda: FakePrinter.calls >= 12)
        wait_for(lambda: not self.get('/api/collector')['request_pending'])
        self.assertEqual(len((self.data / 'history.jsonl').read_text().splitlines()), 2)
        other = self.start('worker.py')
        other.wait(timeout=3)
        self.assertNotEqual(other.returncode, 0)

    def test_persisted_stock_and_parallel_requests(self):
        stock = {'items': [{'part': 'Black toner', 'qty': 3}]}
        self.assertTrue(self.get('/api/stock', 'POST', stock)['ok'])
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            requests = list(pool.map(lambda _: self.get('/api/collect', 'POST'), range(16)))
        self.assertEqual(len({r['request_id'] for r in requests}), 1)
        api = self.processes[0]
        api.terminate()
        api.wait(timeout=3)
        self.start('app.py')
        wait_for(lambda: self.get('/api/health')['ok'])
        self.assertEqual(self.get('/api/stock')['items'][0]['qty'], 3)
        self.assertTrue(self.get('/api/collector')['request_pending'])

    def test_status_detects_stale_heartbeat_and_errors(self):
        path = self.data / 'collector_status.json'
        path.write_text(json.dumps({'heartbeat_at': time.time() - 100, 'started_at': time.time()}))
        self.assertEqual(self.get('/api/collector')['health'], 'unresponsive')
        path.write_text(json.dumps({'heartbeat_at': time.time(), 'started_at': time.time(), 'last_error': 'Printer API error'}))
        self.assertEqual(self.get('/api/collector')['health'], 'degraded')

    def test_dismissal_survives_collection(self):
        self.env['CONFIG_PATH'] = str(Path(self.tmp.name) / 'offline.json')
        Path(self.env['CONFIG_PATH']).write_text(json.dumps({'poll_interval_seconds': 300,
            'http_timeout_seconds': 1, 'printers': [{'id': 'test', 'ip': '127.0.0.1:1'}]}))
        self.start('worker.py')
        wait_for(lambda: len(self.get('/api/state')['alerts']) == 1)
        self.get('/api/dismiss?key=offline', 'POST')
        self.get('/api/collect', 'POST')
        wait_for(lambda: not self.get('/api/collector')['request_pending'])
        self.assertTrue(self.get('/api/state')['alerts'][0]['dismissed'])
        self.get('/api/restore?key=offline', 'POST')
        self.assertFalse(self.get('/api/state')['alerts'][0]['dismissed'])


if __name__ == '__main__':
    unittest.main()
