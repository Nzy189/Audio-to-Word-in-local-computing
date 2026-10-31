import http.client
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

SUMMARY_PROMPT = (
    "你是语音转写文稿的整理助手。输入是一段语音识别的原始转写文字，可能包含同音错别字、语气词和无意义重复。\n"
    "请忽略错别字和语气词，输出这份录音的内容纪要：\n"
    "- 人名、机构名、专有术语按上下文推断正确写法，不要照抄识别错误\n"
    "- 按主题分类组织：每个大类一行标题（格式如【预算】【人员】【进度】），其下用精简要点列出该类的具体信息，每点一行\n"
    "- 大类按重要性排序，只列实际存在的内容，没有的主题不要编造\n"
    "- 最后单独一个【遗留任务】大类：列出所有待办事项，尽量带负责人和期限；全文没有待办则省略这一节\n"
    "- 每点必须是具体信息：做了什么、决定了什么、数字、时间、名字\n"
    '- 禁止泛泛描述（如"讨论了某话题""表达了某种想法"），没有实际信息的内容不要写\n'
    "- 不写引言和套话，不复述原文\n"
    "只输出纪要正文，不要输出任何其他内容。"
)

CORRECT_PROMPT = (
    "你是语音转写文稿的整理助手。输入是一段语音识别的原始转写文字，可能包含同音错别字、语气词和无意义重复。\n"
    "请输出修正后的完整正文：\n"
    "- 修正同音字和明显的识别错误\n"
    '- 删除"额""嗯""哼""啊"等无意义语气词\n'
    "- 删除无意义的重复词句\n"
    "- 不改写句式，不增删信息，不改变原意，不改变语言\n"
    "- 保留原文的分行结构\n"
    "只输出修正后的正文，不要任何前言、解释、标记或代码围栏。"
)

SEGMENT_TARGET = 5000
MAX_WORKERS = 4


class RefineError(Exception):
    pass


class _Retryable(RefineError):
    pass


def _strip_fences(text):
    text = (text or "").strip()
    if text.startswith("```"):
        newline = text.find("\n")
        if newline != -1:
            text = text[newline + 1:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def _request(base_url, model, api_key, system_prompt, user_content, timeout, expected_total, progress=None, progress_interval=30):
    parts = urlsplit(base_url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise RefineError("API 地址格式无效")
    path = (parts.path or "").rstrip("/") + "/chat/completions"
    connection = (http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection)(
        parts.hostname, parts.port, timeout=timeout)
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "stream": True,
    }).encode()
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + api_key, "Accept": "text/event-stream"}
    try:
        connection.request("POST", path, body=body, headers=headers)
        response = connection.getresponse()
        status = response.status
        if status != 200:
            raw = response.read().decode("utf-8", "replace")
            detail = raw[:200].replace("\n", " ").strip()
            suffix = "：" + detail if detail else ""
            if status in (401, 403):
                raise RefineError("API Key 无效或没有权限（HTTP " + str(status) + "）" + suffix)
            if status == 404:
                raise RefineError("API 地址或模型不存在（HTTP 404）" + suffix)
            raise _Retryable("AI 服务返回 HTTP " + str(status) + suffix)
        # 流式读取：超时作用于相邻数据块之间，模型持续输出就不会中断
        content_parts = []
        reasoning_chars = 0
        usage = None
        stream_started = time.monotonic()
        output_started = None
        last_report = stream_started
        while True:
            line = response.readline()
            if not line:
                break
            text_line = line.decode("utf-8", "replace").strip()
            if not text_line or text_line.startswith(":") or not text_line.startswith("data:"):
                continue
            payload = text_line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except ValueError:
                continue
            if isinstance(chunk, dict) and chunk.get("error"):
                message = chunk["error"].get("message") if isinstance(chunk["error"], dict) else chunk["error"]
                raise _Retryable("AI 服务流式返回错误：" + str(message)[:200])
            # usage 通常只在最后一个数据块出现，DeepSeek/Kimi/百炼无需请求参数即返回
            if isinstance(chunk, dict) and isinstance(chunk.get("usage"), dict):
                usage = chunk["usage"]
            choices = chunk.get("choices") or []
            if choices:
                delta = choices[0].get("delta") or {}
                piece = delta.get("content")
                if piece:
                    if output_started is None:
                        output_started = time.monotonic()
                    content_parts.append(piece)
                think = delta.get("reasoning_content")
                if think:
                    reasoning_chars += len(think)
            if progress is not None and time.monotonic() - last_report >= progress_interval:
                last_report = time.monotonic()
                chars = sum(len(part) for part in content_parts)
                eta = None
                if output_started is not None and chars > 0:
                    rate = chars / max(0.001, last_report - output_started)
                    eta = max(0, expected_total - chars) / rate
                progress(chars, reasoning_chars, last_report - stream_started, eta)
        return "".join(content_parts), usage
    except (http.client.HTTPException, OSError) as exc:
        raise _Retryable("无法连接 AI 服务：" + str(exc)[:120])
    finally:
        connection.close()


def _usage_or_estimate(usage, input_chars, output_chars):
    if isinstance(usage, dict) and usage.get("total_tokens") is not None:
        return {
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "estimated": False,
        }
    return {
        "prompt_tokens": int(input_chars * 0.6),
        "completion_tokens": int(output_chars * 0.6),
        "estimated": True,
    }


def summarize(raw_text, base_url, model, api_key, timeout=120, progress=None, progress_interval=30):
    if not (base_url and model and api_key):
        raise RefineError("AI 提炼未配置完整（需要地址、模型和 API Key）")
    if not raw_text or not raw_text.strip():
        raise RefineError("没有可提炼的转写文字")
    expected_total = int(len(raw_text) * 0.06) + 200
    last_error = None
    for attempt in (1, 2):
        try:
            text, usage = _request(base_url, model, api_key, SUMMARY_PROMPT, raw_text, timeout, expected_total, progress, progress_interval)
            summary = _strip_fences(text)
            if not summary:
                raise _Retryable("AI 返回的纪要为空")
            return {"summary": summary, "usage": _usage_or_estimate(usage, len(SUMMARY_PROMPT) + len(raw_text), len(summary))}
        except _Retryable as exc:
            last_error = str(exc)
    raise RefineError(last_error or "AI 纪要生成失败")


def _split_long_line(line, target):
    if len(line) <= target:
        return [line]
    pieces = []
    start = 0
    while start < len(line):
        piece = line[start:start + target]
        if len(piece) < target:
            pieces.append(piece)
            break
        cut = max(piece.rfind(mark) for mark in "。！？；")
        if cut < target // 2:
            cut = target - 1
        pieces.append(piece[:cut + 1])
        start += cut + 1
    return pieces


def _split_segments(text, target=SEGMENT_TARGET):
    segments = []
    buf = []
    buf_len = 0

    def flush():
        nonlocal buf, buf_len
        if buf:
            segments.append((True, "\n".join(buf)))
            buf = []
            buf_len = 0

    for line in text.split("\n"):
        if not line.strip():
            flush()
            segments.append((False, line))
            continue
        for piece in _split_long_line(line, target):
            if buf and buf_len + len(piece) > target:
                flush()
            buf.append(piece)
            buf_len += len(piece)
    flush()
    return segments


def correct_text(raw_text, base_url, model, api_key, timeout=120, max_workers=MAX_WORKERS, on_segment=None):
    if not (base_url and model and api_key):
        raise RefineError("AI 提炼未配置完整（需要地址、模型和 API Key）")
    if not raw_text or not raw_text.strip():
        raise RefineError("没有可提炼的转写文字")
    segments = _split_segments(raw_text)
    llm_segments = [(i, seg) for i, (needs_llm, seg) in enumerate(segments) if needs_llm]
    total = len(llm_segments)
    if total == 0:
        return {"corrected": "\n".join(seg for _, seg in segments),
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "estimated": False}}
    outputs = {}
    usage_lock = threading.Lock()
    usage_sum = {"prompt_tokens": 0, "completion_tokens": 0}
    usage_real = False
    completed = 0

    def run_one(position, ordinal, segment):
        nonlocal completed, usage_real
        last_error = None
        for attempt in (1, 2):
            try:
                text, usage = _request(base_url, model, api_key, CORRECT_PROMPT, segment, timeout, int(len(segment) * 1.1) + 100)
                corrected = _strip_fences(text)
                if not corrected:
                    raise _Retryable("AI 返回内容为空")
                with usage_lock:
                    outputs[position] = corrected
                    if isinstance(usage, dict) and usage.get("total_tokens") is not None:
                        usage_sum["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
                        usage_sum["completion_tokens"] += int(usage.get("completion_tokens") or 0)
                        usage_real = True
                    completed += 1
                    count = completed
                if on_segment is not None:
                    on_segment(count, total)
                return None
            except _Retryable as exc:
                last_error = str(exc)
        return "第 %d/%d 段修正失败：%s" % (ordinal, total, last_error)

    errors = {}
    with ThreadPoolExecutor(max_workers=min(max_workers, total)) as pool:
        futures = [pool.submit(run_one, position, ordinal, segment)
                   for ordinal, (position, segment) in enumerate(llm_segments, 1)]
        for ordinal, future in enumerate(futures, 1):
            error = future.result()
            if error:
                errors[ordinal] = error
    if errors:
        raise RefineError(errors[min(errors)])
    parts = []
    for i, (needs_llm, seg) in enumerate(segments):
        parts.append(outputs[i] if needs_llm else seg)
    corrected = "\n".join(parts)
    if usage_real:
        usage = {"prompt_tokens": usage_sum["prompt_tokens"], "completion_tokens": usage_sum["completion_tokens"], "estimated": False}
    else:
        input_chars = sum(len(seg) for _, seg in llm_segments) + total * len(CORRECT_PROMPT)
        usage = _usage_or_estimate(None, input_chars, len(corrected))
    return {"corrected": corrected, "usage": usage}
