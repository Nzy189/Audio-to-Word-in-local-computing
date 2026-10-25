"""QA-only LAN worker simulator, run inside the isolated QA NAS container."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, value):
        raw = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        mode = Path("/tmp/fault-mode").read_text().strip()
        if self.path == "/v1/health":
            self.reply(200, {"ready": mode != "offline", "busy": mode == "busy"})
        elif mode == "drop":
            self.close_connection = True
        else:
            self.reply(200, {"status": "error"})

    def do_PUT(self):
        length = int(self.headers["Content-Length"])
        while length:
            chunk = self.rfile.read(min(65536, length))
            if not chunk:
                break
            length -= len(chunk)
        self.reply(202, {"ok": True})

    def do_DELETE(self):
        self.reply(200, {"ok": True})


ThreadingHTTPServer(("127.0.0.1", 18999), Handler).serve_forever()
