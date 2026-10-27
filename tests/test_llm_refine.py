import http.server
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "service"))
import llm_refine

OK = json.dumps({"choices": [{"message": {"content": json.dumps(
    {"corrected": "干净原文", "summary": "- 要点"}, ensure_ascii=False)}}]}, ensure_ascii=False)


class Stub(http.server.BaseHTTPRequestHandler):
    calls = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Stub.calls.append(body.get("model", ""))
        model = body.get("model", "")
        if model == "stub-garbage":
            self._send(200, "这不是 JSON")
        elif model == "stub-500":
            self._send(500, "server error")
        elif model == "stub-401":
            self._send(401, json.dumps({"error": {"message": "bad key"}}))
        elif model == "stub-slow":
            time.sleep(6)
            self._send(200, OK)
        elif model == "stub-fence":
            self._send(200, json.dumps({"choices": [{"message": {"content": "```json\n" + json.dumps(
                {"corrected": "围栏原文", "summary": "- 围栏要点"}, ensure_ascii=False) + "\n```"}}]}))
        elif model == "stub-prefix":
            self._send(200, json.dumps({"choices": [{"message": {"content": "结果如下：" + json.dumps(
                {"corrected": "前缀原文", "summary": "- 前缀要点"}, ensure_ascii=False)}}]}))
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

    check("正常返回", ok_result)
    check("代码围栏解析", fence_result)
    check("前缀文本解析", prefix_result)
    check("非JSON重试后失败", garbage_fails_after_retry)
    check("5xx重试后失败", server_error_fails_after_retry)
    check("401不重试", unauthorized_no_retry)
    check("超时失败", timeout_fails)
    check("缺配置报错", missing_config)
    server.shutdown()
    if failures:
        print("FAILED:", failures)
        sys.exit(1)
    print("ALL 8 PASS")


if __name__ == "__main__":
    main()
