"""Stub OpenAI-compatible SSE server for refine QA (runs inside the QA container)."""
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SUMMARY_TEXT = "【测试】\n- 测试要点"
USAGE = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        model = body.get("model", "")
        system = body["messages"][0]["content"]
        user = body["messages"][1]["content"]
        phase = "summary" if "纪要" in system else "correct"
        if model == "stub-500":
            self._plain(500, "server error")
        elif model == "stub-slow":
            time.sleep(8)
            self._stream(self._content(phase, user))
        elif model == "stub-correct-fail" and phase == "correct":
            self._plain(500, "server error")
        else:
            self._stream(self._content(phase, user))

    def _content(self, phase, user):
        return SUMMARY_TEXT if phase == "summary" else "净" + user

    def _stream(self, content):
        n = max(1, len(content) // 3)
        pieces = [content[i:i + n] for i in range(0, len(content), n)] or [""]
        data = b""
        for piece in pieces:
            data += b": keep-alive\n\n"
            data += b"data: " + json.dumps({"choices": [{"delta": {"content": piece}}]}, ensure_ascii=False).encode() + b"\n\n"
        data += b"data: " + json.dumps({"choices": [], "usage": USAGE}).encode() + b"\n\n"
        data += b"data: [DONE]\n\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _plain(self, status, text):
        data = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


ThreadingHTTPServer(("127.0.0.1", 18789), Handler).serve_forever()
