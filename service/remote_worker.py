"""LAN offload client. The NAS retains its audio until a result is committed."""
import http.client
import json
import os
import socket
import time
from urllib.parse import urlsplit


class RemoteUnavailable(Exception):
    def __init__(self, message, code="unavailable"):
        super().__init__(message)
        self.code = code


class TaskCancelled(Exception):
    pass


def network_error(exc):
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return RemoteUnavailable("连接电脑超时，请检查电脑是否开机、内网地址和防火墙", "timeout")
    if isinstance(exc, ConnectionRefusedError):
        return RemoteUnavailable("电脑转写端口拒绝连接，服务可能未启动或端口不正确", "connection_refused")
    if isinstance(exc, socket.gaierror):
        return RemoteUnavailable("无法解析电脑地址，请检查地址或主机名", "dns_error")
    return RemoteUnavailable("与电脑的连接中断或无法建立", "connection_lost")


class RemoteWorker:
    def __init__(self, url):
        self.url = urlsplit(url.rstrip("/"))
        if self.url.scheme not in ("http", "https") or not self.url.hostname or self.url.path not in ("", "/") or self.url.username or self.url.password or self.url.query or self.url.fragment:
            raise ValueError("REMOTE_WORKER_URL must be an HTTP(S) origin")
        self.url.port  # Validate the port before attempting a connection.

    def connection(self, timeout):
        kind = http.client.HTTPSConnection if self.url.scheme == "https" else http.client.HTTPConnection
        return kind(self.url.hostname, self.url.port, timeout=timeout)

    def request(self, method, path, timeout=3, allow_missing=False):
        conn = self.connection(timeout)
        try:
            conn.request(method, path, headers={"Content-Length": "0"})
            response = conn.getresponse()
            raw = response.read(2 * 1024 * 1024 + 1)
            if response.status in (401, 403):
                raise RemoteUnavailable("电脑服务仍要求连接密钥，请把电脑端 GPU 服务更新到新版", "unauthorized")
            if response.status == 404:
                if allow_missing:
                    return {"status": "missing"}
                raise RemoteUnavailable("该地址或端口不是兼容的电脑转写服务", "wrong_service")
            if response.status != 200 or len(raw) > 2 * 1024 * 1024:
                raise RemoteUnavailable("电脑服务返回异常状态", "remote_http_error")
            return json.loads(raw)
        except OSError as exc:
            raise network_error(exc) from exc
        except (ValueError, http.client.HTTPException) as exc:
            raise RemoteUnavailable("电脑服务响应无效，或连接已中断", "invalid_response") from exc
        finally:
            conn.close()

    def upload(self, job_id, source, check_cancel=None):
        conn = self.connection(15)
        try:
            conn.putrequest("PUT", "/v1/jobs/" + job_id)
            conn.putheader("Content-Type", "application/octet-stream")
            conn.putheader("Content-Length", str(source.stat().st_size))
            conn.endheaders()
            deadline = time.monotonic() + 300
            with source.open("rb") as audio:
                while chunk := audio.read(1024 * 1024):
                    if check_cancel:
                        check_cancel()
                    if time.monotonic() > deadline:
                        raise RemoteUnavailable("音频发送到电脑超时", "upload_timeout")
                    conn.send(chunk)
            response = conn.getresponse()
            response.read(4096)
            if response.status in (401, 403):
                raise RemoteUnavailable("电脑服务仍要求连接密钥，请把电脑端 GPU 服务更新到新版", "unauthorized")
            if response.status == 409:
                raise RemoteUnavailable("电脑正在处理其他任务，暂时无法接收录音", "busy")
            if response.status not in (200, 202):
                raise RemoteUnavailable("电脑未能接收音频", "upload_failed")
        except OSError as exc:
            raise network_error(exc) from exc
        except http.client.HTTPException as exc:
            raise RemoteUnavailable("发送音频时连接中断", "upload_failed") from exc
        finally:
            conn.close()

    def probe(self):
        health = self.request("GET", "/v1/health", timeout=2)
        if not isinstance(health, dict) or "ready" not in health:
            raise RemoteUnavailable("该地址不是兼容的电脑转写服务", "wrong_service")
        if health.get("busy"):
            raise RemoteUnavailable("电脑正在处理其他转写任务", "busy")
        if not health.get("ready"):
            messages = {"gpu_memory_low": "电脑显卡空闲显存不足", "cuda_unavailable": "电脑 CUDA 或 GPU 服务不可用", "initializing": "电脑识别模型正在加载"}
            code = health.get("reason", "not_ready")
            raise RemoteUnavailable(messages.get(code, "电脑识别服务尚未就绪，可能正在加载模型或显存不足"), code)
        return health

    def run(self, job_id, source, progress, stop, check_cancel=None):
        if check_cancel:
            check_cancel()
        health = self.probe()
        progress("remote_upload", 1, health.get("name", "电脑 GPU"), "正在通过局域网发送音频")
        self.upload(job_id, source, check_cancel)
        deadline = time.monotonic() + int(os.getenv("REMOTE_JOB_TIMEOUT", "900"))
        failures = 0
        while not stop.is_set():
            if check_cancel:
                check_cancel()
            if time.monotonic() > deadline:
                raise RemoteUnavailable("电脑转写超过等待时限", "job_timeout")
            try:
                result = self.request("GET", "/v1/jobs/" + job_id)
                failures = 0
            except RemoteUnavailable:
                failures += 1
                if failures >= 2:
                    raise
                stop.wait(1)
                continue
            state = result.get("status")
            if state == "done":
                if not isinstance(result.get("text"), str) or not isinstance(result.get("duration"), (int, float)):
                    raise RemoteUnavailable("电脑返回的转写结果不完整", "invalid_result")
                return result
            if state in ("error", "cancelled"):
                raise RemoteUnavailable("电脑转写任务失败或被取消", "gpu_task_failed")
            progress("remote_processing", min(95, max(5, int(result.get("progress", 5)))), result.get("backend_name", "电脑 GPU"), "电脑 GPU 正在转写")
            stop.wait(1)
        raise RemoteUnavailable("NAS 服务正在停止，保留录音等待恢复", "stopping")

    def cancel(self, job_id):
        try:
            self.request("DELETE", "/v1/jobs/" + job_id, timeout=2)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                result = self.request("GET", "/v1/jobs/" + job_id, timeout=2, allow_missing=True)
                if result.get("status") in ("missing", "cancelled"):
                    return True
                time.sleep(0.2)
        except RemoteUnavailable:
            pass
        return False

    def release(self, job_id):
        # Acts as acknowledgement after success, or a cancellation request after failure.
        try:
            self.request("DELETE", "/v1/jobs/" + job_id, timeout=2)
        except RemoteUnavailable:
            pass  # The PC independently expires results and removes all audio.
