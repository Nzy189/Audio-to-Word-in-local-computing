"""推断录音的录制时间（纯标准库，可本地单测）。

优先级：音频内嵌元数据 > 文件名里的日期时间 > 浏览器提供的文件修改时间。
返回 (unix 秒, 来源)；来源为 "metadata" / "filename" / "file_mtime"，都推断不出时返回 (None, "")。
"""
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone

MIN_TS = datetime(2000, 1, 1, tzinfo=timezone.utc).timestamp()
SOURCES = ("metadata", "filename", "file_mtime", "manual")

# 按可靠程度排序：带时区的苹果录制日期最可靠，其次是通用 creation_time 与 WAV/ID3 日期
METADATA_KEYS = (
    "com.apple.quicktime.creationdate",
    "creation_time",
    "date_recorded",
    "origination_date",
    "date",
    "creation_date",
    "icrd",
)

_FILENAME_PATTERNS = (
    # 20261105_143022 / 20261105-143022 / 20261105T143022 / 20261105143022
    re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})[ _\-T]?(\d{2})(\d{2})(\d{2})(?!\d)"),
    # 2026-11-05 14.30.22 / 2026_11_05-14-30-22 / 2026-11-05T14:30:22 / 2026年11月05日 14时30分22秒
    re.compile(r"(?<!\d)(20\d{2})[-_.年](\d{1,2})[-_.月](\d{1,2})日?[ _\-T]*(\d{1,2})[.:\-_时](\d{1,2})(?:[.:\-_分](\d{1,2})秒?)?(?!\d)"),
)


def plausible(ts, now=None):
    now = time.time() if now is None else now
    return ts is not None and MIN_TS <= ts <= now + 86400


def local_tz(tz_offset_minutes):
    """tz_offset_minutes 与 JS Date.getTimezoneOffset() 同号：UTC+4 为 -240。"""
    try:
        minutes = int(tz_offset_minutes)
    except (TypeError, ValueError):
        return timezone.utc
    if abs(minutes) > 14 * 60:
        return timezone.utc
    return timezone(timedelta(minutes=-minutes))


def parse_metadata_value(value, tz):
    """解析元数据中的时间字符串，无时区信息时按 tz（ISO 带 Z 的视为 UTC）。"""
    text = (value or "").strip().strip('"')
    if not text:
        return None
    text = re.sub(r"\.\d+", "", text)  # 去掉小数秒
    text = text.replace("Z", "+00:00")
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)  # +0400 -> +04:00
    text = re.sub(r"^(\d{4})[:/](\d{2})[:/](\d{2})", r"\1-\2-\3", text)  # 2026:11:05 -> 2026-11-05
    for candidate in (text, text.replace(" ", "T", 1)):
        try:
            moment = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if moment.tzinfo is None:
            if len(candidate) <= 10:  # 只有日期没有时间，精度不足
                return None
            moment = moment.replace(tzinfo=tz)
        return moment.timestamp()
    return None


def from_metadata(tags, tz, now=None):
    lowered = {str(k).strip().lower(): v for k, v in (tags or {}).items()}
    for key in METADATA_KEYS:
        if key not in lowered:
            continue
        value = lowered[key]
        if key == "origination_date" and lowered.get("origination_time"):
            value = value + " " + lowered["origination_time"].replace("-", ":")
        ts = parse_metadata_value(value, tz)
        if plausible(ts, now):
            return ts
    return None


def from_filename(name, tz, now=None):
    for pattern in _FILENAME_PATTERNS:
        for match in pattern.finditer(name or ""):
            parts = [int(p) if p else 0 for p in match.groups()]
            try:
                moment = datetime(*parts, tzinfo=tz)
            except ValueError:
                continue
            ts = moment.timestamp()
            if plausible(ts, now):
                return ts
    return None


def from_mtime(last_modified_ms, received_at, now=None):
    """浏览器 File.lastModified；部分手机选择器拿不到时会填当前时间，贴近上传时刻的值不采用。"""
    try:
        ts = float(last_modified_ms) / 1000
    except (TypeError, ValueError):
        return None
    if not plausible(ts, now) or ts > received_at - 30:
        return None
    return ts


def parse_ffmpeg_info(output):
    """解析 `ffmpeg -i` 输出里第一个输入的全局 Metadata 块（Stream 内的元数据不采用）。"""
    tags = {}
    inside = False
    for line in (output or "").splitlines():
        if not inside:
            if line.strip() == "Metadata:" and line.startswith("  ") and not line.startswith("    "):
                inside = True
            continue
        if not line.startswith("    "):
            break
        key, sep, value = line.strip().partition(":")
        key = key.strip().lower()
        if sep and key:
            tags.setdefault(key, value.strip())
    return tags


def read_tags(path, timeout=20):
    # 不给输出文件时 ffmpeg 以非零码退出，但已在 stderr 打印输入信息，这正是需要的
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-protocol_whitelist", "file", "-i", str(path)]
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    return parse_ffmpeg_info(result.stderr.decode("utf-8", "replace"))


def detect(path, name, last_modified_ms=None, tz_offset_minutes=None, received_at=None, tags=None):
    now = time.time()
    received_at = now if received_at is None else received_at
    tz = local_tz(tz_offset_minutes)
    if tags is None:
        tags = read_tags(path)
    ts = from_metadata(tags, tz, now)
    if ts is not None:
        return ts, "metadata"
    ts = from_filename(name, tz, now)
    if ts is not None:
        return ts, "filename"
    ts = from_mtime(last_modified_ms, received_at, now)
    if ts is not None:
        return ts, "file_mtime"
    return None, ""
