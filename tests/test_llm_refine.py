import http.server
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "service"))
import llm_refine

SUMMARY_TEXT = "【主题】\n- 要点一\n- 要点二"
USAGE = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
SEG_USAGE = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


class Stub(http.server.BaseHTTPRequestHandler):
    calls = []
    flaky_fails = 0

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        system = body["messages"][0]["content"]
        user = body["messages"][1]["content"]
        phase = "summary" if "纪要" in system else "correct"
        model = body.get("model", "")
        Stub.calls.append((model, phase))
        if "FAILALL" in user:
            self._send(500, "server error")
            return
        if "temperature" in body:
            self._send(400, json.dumps({"error": {"message": "Parameter 'temperature' is not supported for this model."}}))
            return
        if body.get("stream") is not True:
            self._send(400, json.dumps({"error": {"message": "客户端必须使用流式请求"}}))
            return
        if model == "stub-400":
            self._send(400, json.dumps({"error": {"message": "参数无效：演示用的错误详情"}}, ensure_ascii=False))
        elif model == "stub-500":
            self._send(500, "server error")
        elif model == "stub-401":
            self._send(401, json.dumps({"error": {"message": "bad key"}}))
        elif model == "stub-slow":
            time.sleep(6)
            self._stream(SUMMARY_TEXT, USAGE)
        elif model == "stub-stream-error":
            self._stream_error()
        elif model == "stub-fence":
            self._stream("```\n" + SUMMARY_TEXT + "\n```", USAGE)
        elif model == "stub-empty":
            self._stream("", USAGE)
        elif model == "stub-no-usage":
            self._stream(SUMMARY_TEXT if phase == "summary" else "净" + user, None)
        elif model == "stub-flaky":
            if phase == "correct" and "FAILME" in user and Stub.flaky_fails == 0:
                Stub.flaky_fails += 1
                self._send(500, "server error")
            else:
                self._stream(SUMMARY_TEXT if phase == "summary" else "净" + user, USAGE if phase == "summary" else SEG_USAGE)
        elif model == "stub-drip":
            self._drip()
        else:
            self._stream(SUMMARY_TEXT if phase == "summary" else "净" + user, USAGE if phase == "summary" else SEG_USAGE)

    def _stream(self, content, usage):
        n = max(1, len(content) // 3)
        pieces = [content[i:i + n] for i in range(0, len(content), n)] or [""]
        body = b""
        for piece in pieces:
            body += b": keep-alive\n\n"
            body += b"data: " + json.dumps({"choices": [{"delta": {"content": piece}}]}, ensure_ascii=False).encode() + b"\n\n"
        if usage is not None:
            body += b"data: " + json.dumps({"choices": [], "usage": usage}).encode() + b"\n\n"
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

    def _drip(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for think in ("思考片段一", "思考片段二", "思考片段三"):
            data = b"data: " + json.dumps({"choices": [{"delta": {"reasoning_content": think}}]}, ensure_ascii=False).encode() + b"\n\n"
            self.wfile.write(data)
            self.wfile.flush()
            time.sleep(0.05)
        n = max(1, len(SUMMARY_TEXT) // 10)
        for piece in [SUMMARY_TEXT[i:i + n] for i in range(0, len(SUMMARY_TEXT), n)]:
            data = b"data: " + json.dumps({"choices": [{"delta": {"content": piece}}]}, ensure_ascii=False).encode() + b"\n\n"
            self.wfile.write(data)
            self.wfile.flush()
            time.sleep(0.05)
        self.wfile.write(b"data: " + json.dumps({"choices": [], "usage": USAGE}).encode() + b"\n\n")
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

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

    def summary_ok():
        r = llm_refine.summarize("原文", base, "stub-ok", "sk-test", timeout=5)
        assert r["summary"] == SUMMARY_TEXT, r
        assert r["usage"]["prompt_tokens"] == 100 and r["usage"]["completion_tokens"] == 20 and r["usage"]["estimated"] is False, r

    def summary_fence():
        r = llm_refine.summarize("原文", base, "stub-fence", "sk-test", timeout=5)
        assert r["summary"] == SUMMARY_TEXT, r

    def summary_empty_retries():
        Stub.calls = []
        expect_error(lambda: llm_refine.summarize("原文", base, "stub-empty", "sk-test", timeout=5), "为空")
        assert len(Stub.calls) == 2, Stub.calls

    def correct_single():
        r = llm_refine.correct_text("一句话", base, "stub-ok", "sk-test", timeout=5)
        assert r["corrected"] == "净一句话", r
        assert r["usage"]["prompt_tokens"] == 10 and r["usage"]["completion_tokens"] == 5 and r["usage"]["estimated"] is False, r

    def correct_parallel():
        lines = ["第%d段%s" % (i, "内容" * 1600) for i in range(6)]
        text = "\n".join(lines)
        counts = []
        r = llm_refine.correct_text(text, base, "stub-ok", "sk-test", timeout=15,
                                    on_segment=lambda done, total: counts.append((done, total)))
        segs = llm_refine._split_segments(text)
        n = sum(1 for needs, _ in segs if needs)
        assert n >= 3, "应切成多段，实际 %d" % n
        assert r["corrected"] == "\n".join("净" + seg for needs, seg in segs if needs), r["corrected"][:80]
        assert sorted(counts) == [(i, n) for i in range(1, n + 1)], counts
        assert r["usage"]["prompt_tokens"] == 10 * n and r["usage"]["completion_tokens"] == 5 * n, r

    def correct_segment_fail():
        text = "\n".join(["甲" * 3000, "FAILALL" + "乙" * 3000, "丙" * 3000])
        Stub.calls = []
        expect_error(lambda: llm_refine.correct_text(text, base, "stub-ok", "sk-test", timeout=15), "第 2/3 段")
        assert len([c for c in Stub.calls if c[1] == "correct"]) == 4, Stub.calls

    def correct_retry_success():
        text = "\n".join(["甲" * 3000, "FAILME" + "乙" * 3000, "丙" * 3000])
        Stub.calls = []
        Stub.flaky_fails = 0
        r = llm_refine.correct_text(text, base, "stub-flaky", "sk-test", timeout=15)
        assert "净FAILME" in r["corrected"] and "净丙" in r["corrected"], r["corrected"][:80]
        assert Stub.flaky_fails == 1
        assert len([c for c in Stub.calls if c[1] == "correct"]) == 4, Stub.calls

    def usage_estimate():
        r = llm_refine.summarize("原文", base, "stub-no-usage", "sk-test", timeout=5)
        assert r["usage"]["estimated"] is True and r["usage"]["prompt_tokens"] > 0 and r["usage"]["completion_tokens"] > 0, r

    def split_aggregate():
        segs = llm_refine._split_segments("a" * 2000 + "\n" + "b" * 2000 + "\n" + "c" * 2000)
        assert [needs for needs, _ in segs] == [True, True], segs
        assert segs[0][1] == "a" * 2000 + "\n" + "b" * 2000, segs

    def split_blank_preserved():
        segs = llm_refine._split_segments("甲\n\n乙")
        assert segs == [(True, "甲"), (False, ""), (True, "乙")], segs
        r = llm_refine.correct_text("甲\n\n乙", base, "stub-ok", "sk-test", timeout=5)
        assert r["corrected"] == "净甲\n\n净乙", r

    def split_long_line():
        line = "无标点" * 2500
        segs = llm_refine._split_segments(line)
        assert len(segs) == 2 and all(needs for needs, _ in segs), segs
        assert "".join(seg for _, seg in segs) == line
        line2 = "句子。" * 2500
        segs2 = llm_refine._split_segments(line2)
        assert len(segs2) >= 2 and "".join(seg for _, seg in segs2) == line2

    def unauthorized_no_retry():
        Stub.calls = []
        expect_error(lambda: llm_refine.summarize("原文", base, "stub-401", "sk-test", timeout=5), "Key")
        assert len(Stub.calls) == 1, Stub.calls

    def server_error_retries():
        Stub.calls = []
        expect_error(lambda: llm_refine.summarize("原文", base, "stub-500", "sk-test", timeout=5), "500")
        assert len(Stub.calls) == 2, Stub.calls

    def error_detail_shown():
        Stub.calls = []
        expect_error(lambda: llm_refine.summarize("原文", base, "stub-400", "sk-test", timeout=5), "演示用的错误详情")
        assert len(Stub.calls) == 2, Stub.calls

    def stream_error_shown():
        Stub.calls = []
        expect_error(lambda: llm_refine.summarize("原文", base, "stub-stream-error", "sk-test", timeout=5), "流内错误")
        assert len(Stub.calls) == 2, Stub.calls

    def timeout_fails():
        expect_error(lambda: llm_refine.summarize("原文", base, "stub-slow", "sk-test", timeout=2), "连接")

    def missing_config():
        expect_error(lambda: llm_refine.summarize("原文", "", "m", "k"), "配置")
        expect_error(lambda: llm_refine.summarize("", base, "m", "k"), "文字")
        expect_error(lambda: llm_refine.correct_text("原文", base, "", "k"), "配置")
        expect_error(lambda: llm_refine.correct_text(" ", base, "m", "k"), "文字")

    def progress_reports():
        reports = []
        r = llm_refine.summarize("原文", base, "stub-drip", "sk-test", timeout=10,
                                 progress=lambda chars, thinking, elapsed, eta: reports.append((chars, thinking, elapsed, eta)),
                                 progress_interval=0.1)
        assert r["summary"] == SUMMARY_TEXT, r
        assert len(reports) >= 2, reports
        assert all(reports[i][0] <= reports[i + 1][0] for i in range(len(reports) - 1)), reports
        assert any(rep[1] > 0 for rep in reports), reports
        assert any(rep[3] is not None for rep in reports), reports

    check("纪要正常返回与usage实测", summary_ok)
    check("纪要围栏剥离", summary_fence)
    check("纪要空输出重试后失败", summary_empty_retries)
    check("修正短文本单段", correct_single)
    check("修正多段并行拼接与usage求和", correct_parallel)
    check("修正段失败含段号", correct_segment_fail)
    check("修正段重试成功", correct_retry_success)
    check("无usage时估算", usage_estimate)
    check("切段-多行聚合", split_aggregate)
    check("切段-空行保留", split_blank_preserved)
    check("切段-超长单行硬切", split_long_line)
    check("401不重试", unauthorized_no_retry)
    check("5xx重试后失败", server_error_retries)
    check("错误详情透出", error_detail_shown)
    check("流内错误透出", stream_error_shown)
    check("超时失败", timeout_fails)
    check("缺配置报错", missing_config)
    check("进度回调", progress_reports)
    server.shutdown()
    if failures:
        print("FAILED:", failures)
        sys.exit(1)
    print("ALL 18 PASS")


if __name__ == "__main__":
    main()
