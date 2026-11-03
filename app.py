"""Web server dashboard + collector berkala.

Menjalankan collector di background thread, lalu menyajikan dashboard statis
dan endpoint JSON.

Jalankan: py app.py  -> buka http://localhost:8080
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import collector

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")
HOST = "0.0.0.0"
PORT = 8080


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # sembunyikan log request bawaan
        pass

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, relpath):
        path = os.path.normpath(os.path.join(WEB_DIR, relpath.lstrip("/")))
        if not path.startswith(WEB_DIR) or not os.path.isfile(path):
            self.send_error(404)
            return
        ctype = "text/html; charset=utf-8"
        if path.endswith(".js"):
            ctype = "application/javascript; charset=utf-8"
        elif path.endswith(".css"):
            ctype = "text/css; charset=utf-8"
        with open(path, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send_file("index.html")
        elif path == "/api/state":
            state = collector.load_json(collector.STATE_PATH, {"printers": [], "alerts": []})
            self._send_json(state)
        elif path == "/api/stock":
            stock = collector.load_json(collector.STOCK_PATH, {"items": []})
            self._send_json(stock)
        elif path == "/api/collect":
            state = collector.run_once(COLLECT_CONFIG)
            self._send_json(state)
        else:
            self._send_file(path)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8") if length else ""
        params = urllib.parse.parse_qs(body)
        path = self.path.split("?", 1)[0]

        if path == "/api/stock":
            try:
                data = json.loads(body) if body else {}
            except json.JSONDecodeError:
                self._send_json({"ok": False, "error": "Body bukan JSON yang valid."}, code=400)
                return
            result = collector.save_stock(data)
            self._send_json(result, code=200 if result.get("ok") else 400)
        elif path == "/api/dismiss":
            key = (params.get("key") or [""])[0]
            self._send_json(collector.dismiss_alert(key))
        elif path == "/api/restore":
            key = (params.get("key") or [None])[0]
            self._send_json(collector.restore_alert(key))
        else:
            self.send_error(404)


def collector_loop(config):
    interval = int(config.get("poll_interval_seconds", 300))
    while True:
        try:
            collector.run_once(config)
        except Exception as exc:  # noqa: BLE001
            print(f"[collector] error: {exc}")
        time.sleep(interval)


COLLECT_CONFIG = {}


def main():
    global COLLECT_CONFIG
    COLLECT_CONFIG = collector.load_json(collector.CONFIG_PATH, {"printers": [], "thresholds": {}})

    # poll pertama saat start, lalu berkala
    try:
        collector.run_once(COLLECT_CONFIG)
    except Exception as exc:  # noqa: BLE001
        print(f"[startup] poll awal gagal: {exc}")

    threading.Thread(target=collector_loop, args=(COLLECT_CONFIG,), daemon=True).start()

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Dashboard siap di http://localhost:{PORT}  (Ctrl+C untuk berhenti)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBerhenti.")


if __name__ == "__main__":
    main()
