import http.client
import json
from urllib.parse import urlsplit

PROMPT = (
    "你是语音转写文稿的整理助手。输入是一段语音识别的原始转写文字，可能包含同音错别字、语气词和无意义重复。\n"
    "请输出严格的 JSON 对象，包含两个字段：\n"
    '"corrected"：优化后的完整原文。\n'
    "- 修正同音字和明显的识别错误\n"
    '- 删除"额""嗯""哼""啊"等无意义语气词\n'
    "- 删除无意义的重复词句\n"
    "- 不改写句式，不增删信息，不改变原意，不改变语言\n"
    "- 保留原文的段落结构\n"
    '"summary"：内容概要。\n'
    "- 用精简的要点列表（bullet points）呈现，每点一行\n"
    "- 每点必须是具体信息：做了什么、决定了什么、数字、时间、名字、待办事项\n"
    '- 禁止泛泛描述（如"讨论了某话题""表达了某种想法"），没有实际信息的内容不要写\n'
    "- 不写引言和套话，不复述原文\n"
    '只输出 JSON，格式：{"corrected": "...", "summary": "..."}，不要输出任何其他内容。'
)


class RefineError(Exception):
    pass


class _Retryable(RefineError):
    pass


def _parse_content(content):
    text = (content or "").strip()
    if text.startswith("```"):
        newline = text.find("\n")
        if newline != -1:
            text = text[newline + 1:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    text = text.strip()
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


def _request(base_url, model, api_key, user_content, timeout):
    parts = urlsplit(base_url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise RefineError("API 地址格式无效")
    path = (parts.path or "").rstrip("/") + "/chat/completions"
    connection = (http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection)(
        parts.hostname, parts.port, timeout=timeout)
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": user_content},
        ],
        "stream": False,
    }).encode()
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + api_key}
    try:
        connection.request("POST", path, body=body, headers=headers)
        response = connection.getresponse()
        status = response.status
        raw = response.read().decode("utf-8", "replace")
    except (http.client.HTTPException, OSError) as exc:
        raise _Retryable("无法连接 AI 服务：" + str(exc)[:120])
    finally:
        connection.close()
    if status != 200:
        detail = raw[:200].replace("\n", " ").strip()
        suffix = "：" + detail if detail else ""
        if status in (401, 403):
            raise RefineError("API Key 无效或没有权限（HTTP " + str(status) + "）" + suffix)
        if status == 404:
            raise RefineError("API 地址或模型不存在（HTTP 404）" + suffix)
        raise _Retryable("AI 服务返回 HTTP " + str(status) + suffix)
    return raw


def refine(raw_text, base_url, model, api_key, timeout=120):
    if not (base_url and model and api_key):
        raise RefineError("AI 提炼未配置完整（需要地址、模型和 API Key）")
    if not raw_text or not raw_text.strip():
        raise RefineError("没有可提炼的转写文字")
    user_content = raw_text
    last_error = None
    for attempt in (1, 2):
        try:
            raw = _request(base_url, model, api_key, user_content, timeout)
            payload = json.loads(raw)
            content = payload["choices"][0]["message"]["content"]
            result = _parse_content(content)
            corrected = str(result.get("corrected") or "").strip()
            summary = str(result.get("summary") or "").strip()
            if not corrected and not summary:
                raise _Retryable("AI 返回内容为空")
            return {"corrected": corrected, "summary": summary}
        except _Retryable as exc:
            last_error = str(exc)
        except RefineError:
            raise
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            last_error = "AI 返回格式无法解析：" + str(exc)[:120]
            if attempt == 1:
                user_content = raw_text + "\n\n（请务必只输出 JSON 对象，不要包含任何其他文字。）"
    raise RefineError(last_error or "AI 提炼失败")
