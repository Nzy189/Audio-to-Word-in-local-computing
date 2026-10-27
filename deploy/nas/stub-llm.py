"""Stub OpenAI-compatible server for refine QA (runs inside the QA container)."""
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OK = json.dumps({"choices": [{"message": {"content": json.dumps(
    {"corrected": "这是优化后的测试原文", "summary": "- 测试要点"}, ensure_ascii=False)}}]}, ensure_ascii=False)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        model = body.get("model", "")
        if model == "stub-garbage":
            self._send(200, "这不是 JSON")
        elif model == "stub-500":
            self._send(500, "server error")
        elif model == "stub-slow":
            time.sleep(8)
            self._send(200, OK)
        else:
            self._send(200, OK)

    def _send(self, status, text):
        data = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


ThreadingHTTPServer(("127.0.0.1", 18789), Handler).serve_forever()
