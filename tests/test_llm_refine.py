import http.server
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "service"))
import llm_refine

OK_CONTENT = json.dumps({"corrected": "干净原文", "summary": "- 要点"}, ensure_ascii=False)


class Stub(http.server.BaseHTTPRequestHandler):
    calls = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Stub.calls.append(body.get("model", ""))
        if "temperature" in body:
            self._send(400, json.dumps({"error": {"code": "invalid_parameter_error", "message": "Parameter 'temperature' is not supported for this model."}}))
            return
        if body.get("stream") is not True:
            self._send(400, json.dumps({"error": {"message": "客户端必须使用流式请求"}}))
            return
        model = body.get("model", "")
        if model == "stub-garbage":
            self._stream("这不是 JSON")
        elif model == "stub-stream-error":
            self._stream_error()
        elif model == "stub-400":
            self._send(400, json.dumps({"error": {"message": "参数无效：演示用的错误详情"}}, ensure_ascii=False))
        elif model == "stub-500":
            self._send(500, "server error")
        elif model == "stub-401":
            self._send(401, json.dumps({"error": {"message": "bad key"}}))
        elif model == "stub-slow":
            time.sleep(6)
            self._stream(OK_CONTENT)
        elif model == "stub-fence":
            self._stream("```json\n" + json.dumps(
                {"corrected": "围栏原文", "summary": "- 围栏要点"}, ensure_ascii=False) + "\n```")
        elif model == "stub-prefix":
            self._stream("结果如下：" + json.dumps(
                {"corrected": "前缀原文", "summary": "- 前缀要点"}, ensure_ascii=False))
        elif model == "stub-nonobject":
            self._stream('"只是一个字符串"')
        elif model == "stub-drip":
            n = max(1, len(OK_CONTENT) // 10)
            pieces = [OK_CONTENT[i:i + n] for i in range(0, len(OK_CONTENT), n)]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for think in ("思考片段一", "思考片段二", "思考片段三"):
                data = b"data: " + json.dumps({"choices": [{"delta": {"reasoning_content": think}}]}, ensure_ascii=False).encode() + b"\n\n"
                self.wfile.write(data)
                self.wfile.flush()
                time.sleep(0.05)
            for piece in pieces:
                data = b"data: " + json.dumps({"choices": [{"delta": {"content": piece}}]}, ensure_ascii=False).encode() + b"\n\n"
                self.wfile.write(data)
                self.wfile.flush()
                time.sleep(0.05)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        else:
            self._stream(OK_CONTENT)

    def _stream(self, content):
        n = max(1, len(content) // 3)
        pieces = [content[i:i + n] for i in range(0, len(content), n)] or [""]
        body = b""
        for piece in pieces:
            body += b": keep-alive\n\n"
            body += b"data: " + json.dumps({"choices": [{"delta": {"content": piece}}]}, ensure_ascii=False).encode() + b"\n\n"
        body += b"data: [DONE]\n\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream_error(self):
        body = b"data: " + json.dumps({"error": {"message": "流式中途出错：演示用的流内错误"}}, ensure_ascii=False).encode() + b"\n\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send(self, status, text):
        data = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def expect_error(fn, fragment):
    try:
        fn()
    except llm_refine.RefineError as exc:
        assert fragment in str(exc), "错误信息不符: " + str(exc)
    else:
        raise AssertionError("应当抛出 RefineError")


def main():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d/v1" % server.server_address[1]
    failures = []

    def check(name, fn):
        try:
            fn()
            print("PASS", name)
        except Exception as exc:
            failures.append(name)
            print("FAIL", name, repr(exc))

    def ok_result():
        r = llm_refine.refine("原文", base, "stub-ok", "sk-test", timeout=5)
        assert r["corrected"] == "干净原文" and r["summary"] == "- 要点", r

    def fence_result():
        r = llm_refine.refine("原文", base, "stub-fence", "sk-test", timeout=5)
        assert r["corrected"] == "围栏原文", r

    def prefix_result():
        r = llm_refine.refine("原文", base, "stub-prefix", "sk-test", timeout=5)
        assert r["corrected"] == "前缀原文", r

    def garbage_fails_after_retry():
        Stub.calls = []
        expect_error(lambda: llm_refine.refine("原文", base, "stub-garbage", "sk-test", timeout=5), "解析")
        assert len(Stub.calls) == 2, Stub.calls

    def server_error_fails_after_retry():
        Stub.calls = []
        expect_error(lambda: llm_refine.refine("原文", base, "stub-500", "sk-test", timeout=5), "500")
        assert len(Stub.calls) == 2, Stub.calls

    def unauthorized_no_retry():
        Stub.calls = []
        expect_error(lambda: llm_refine.refine("原文", base, "stub-401", "sk-test", timeout=5), "Key")
        assert len(Stub.calls) == 1, Stub.calls

    def timeout_fails():
        expect_error(lambda: llm_refine.refine("原文", base, "stub-slow", "sk-test", timeout=2), "连接")

    def missing_config():
        expect_error(lambda: llm_refine.refine("原文", "", "m", "k"), "配置")
        expect_error(lambda: llm_refine.refine("", base, "m", "k"), "文字")

    def non_object_fails_after_retry():
        Stub.calls = []
        expect_error(lambda: llm_refine.refine("原文", base, "stub-nonobject", "sk-test", timeout=5), "解析")
        assert len(Stub.calls) == 2, Stub.calls

    def error_body_shown():
        Stub.calls = []
        expect_error(lambda: llm_refine.refine("原文", base, "stub-400", "sk-test", timeout=5), "演示用的错误详情")
        assert len(Stub.calls) == 2, Stub.calls

    def stream_error_shown():
        Stub.calls = []
        expect_error(lambda: llm_refine.refine("原文", base, "stub-stream-error", "sk-test", timeout=5), "流内错误")
        assert len(Stub.calls) == 2, Stub.calls

    def progress_reports():
        reports = []
        r = llm_refine.refine("原文", base, "stub-drip", "sk-test", timeout=10,
                              progress=lambda chars, thinking, elapsed: reports.append((chars, thinking, elapsed)),
                              progress_interval=0.1)
        assert r["corrected"] == "干净原文", r
        assert len(reports) >= 2, reports
        assert all(reports[i][0] <= reports[i + 1][0] for i in range(len(reports) - 1)), reports
        assert any(rep[1] > 0 for rep in reports), reports

    check("正常返回", ok_result)
    check("代码围栏解析", fence_result)
    check("前缀文本解析", prefix_result)
    check("非JSON重试后失败", garbage_fails_after_retry)
    check("5xx重试后失败", server_error_fails_after_retry)
    check("401不重试", unauthorized_no_retry)
    check("超时失败", timeout_fails)
    check("缺配置报错", missing_config)
    check("非对象JSON重试后失败", non_object_fails_after_retry)
    check("错误详情透出", error_body_shown)
    check("流内错误透出", stream_error_shown)
    check("进度回调", progress_reports)
    server.shutdown()
    if failures:
        print("FAILED:", failures)
        sys.exit(1)
    print("ALL 12 PASS")


if __name__ == "__main__":
    main()
