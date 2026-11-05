"""Backend API only. Printer polling runs separately in worker.py."""
import json
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import collector
import runtime

HOST = os.environ.get('HOST', '0.0.0.0')
PORT = int(os.environ.get('PORT', '8080'))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == '/api/health':
            self._send_json({'ok': True, 'service': 'backend'})
        elif path == '/api/state':
            self._send_json(collector.load_json(collector.STATE_PATH, {'printers': [], 'alerts': []}))
        elif path == '/api/stock':
            self._send_json(collector.load_json(collector.STOCK_PATH, {'items': []}))
        elif path == '/api/collector':
            self._send_json(runtime.collector_status())
        elif path == '/api/collect':
            self._send_json({'ok': False, 'error': 'Use POST /api/collect to queue a poll.'}, 405)
        else:
            self._send_json({'ok': False, 'error': 'Not found'}, 404)

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length') or 0)
            if length < 0 or length > 1024 * 1024:
                self._send_json({'ok': False, 'error': 'Request too large'}, 413)
                return
            body = self.rfile.read(length).decode('utf-8') if length else ''
        except (ValueError, UnicodeDecodeError):
            self._send_json({'ok': False, 'error': 'Invalid request'}, 400)
            return
        url = urllib.parse.urlsplit(self.path)
        params = urllib.parse.parse_qs(url.query)
        params.update(urllib.parse.parse_qs(body))
        if url.path == '/api/collect':
            self._send_json(runtime.request_collection(), 202)
        elif url.path == '/api/stock':
            try:
                data = json.loads(body) if body else {}
            except json.JSONDecodeError:
                self._send_json({'ok': False, 'error': 'Invalid JSON'}, 400)
                return
            result = collector.save_stock(data)
            self._send_json(result, 200 if result.get('ok') else 400)
        elif url.path == '/api/dismiss':
            key = (params.get('key') or [''])[0]
            self._send_json(collector.dismiss_alert(key))
        elif url.path == '/api/restore':
            key = (params.get('key') or [None])[0]
            self._send_json(collector.restore_alert(key))
        else:
            self._send_json({'ok': False, 'error': 'Not found'}, 404)


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f'Backend listening on {HOST}:{PORT}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
