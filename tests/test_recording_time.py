"""录制时间推断单测（纯标准库；若本机有 ffmpeg，额外验证真实文件元数据读取）。"""
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "service"))
import recording_time as rt

DUBAI = -240  # JS getTimezoneOffset()：UTC+4
TZ = timezone(timedelta(hours=4))
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=TZ).timestamp()
passed = 0


def check(label, actual, expected):
    global passed
    assert actual == expected, "%s: %r != %r" % (label, actual, expected)
    passed += 1
    print("PASS", label)


def local(*parts):
    return datetime(*parts, tzinfo=TZ).timestamp()


tz = rt.local_tz(DUBAI)
check("时区换算", tz.utcoffset(None), timedelta(hours=4))
check("非法时区回落 UTC", rt.local_tz("abc"), timezone.utc)

# 文件名
for name, expected in (
    ("20261103_143022.m4a", local(2026, 11, 3, 14, 30, 22)),
    ("Recording_20261103-143022.mp3", local(2026, 11, 3, 14, 30, 22)),
    ("录音 2026-11-03 14.30.22.m4a", local(2026, 11, 3, 14, 30, 22)),
    ("2026年11月3日 9时05分.m4a", local(2026, 11, 3, 9, 5, 0)),
    ("会议_2026-11-03T08:01:02.wav", local(2026, 11, 3, 8, 1, 2)),
    ("新录音 3.m4a", None),
    ("20261399_250000.m4a", None),
    ("20301103_143022.m4a", None),  # 未来时间不可信
):
    check("文件名 " + name, rt.from_filename(name, tz, NOW), expected)

# 元数据
check("元数据 creation_time UTC", rt.from_metadata({"creation_time": "2026-11-03T10:30:22.000000Z"}, tz, NOW), local(2026, 11, 3, 14, 30, 22))
check("元数据 苹果带时区", rt.from_metadata({"com.apple.quicktime.creationdate": "2026-11-03T14:30:22+0400", "creation_time": "2020-01-01T00:00:00Z"}, tz, NOW), local(2026, 11, 3, 14, 30, 22))
check("元数据 WAV bext", rt.from_metadata({"origination_date": "2026-11-03", "origination_time": "14-30-22"}, tz, NOW), local(2026, 11, 3, 14, 30, 22))
check("元数据 EXIF 风格", rt.from_metadata({"date": "2026:11:03 14:30:22"}, tz, NOW), local(2026, 11, 3, 14, 30, 22))
check("元数据 只有年份忽略", rt.from_metadata({"date": "2026"}, tz, NOW), None)
check("元数据 1904 零值忽略", rt.from_metadata({"creation_time": "1904-01-01T00:00:00Z"}, tz, NOW), None)

# 文件修改时间
check("修改时间 正常", rt.from_mtime(str(int(local(2026, 11, 3, 14, 30) * 1000)), NOW, NOW), local(2026, 11, 3, 14, 30))
check("修改时间 贴近上传时刻忽略", rt.from_mtime(str(int((NOW - 5) * 1000)), NOW, NOW), None)
check("修改时间 非法", rt.from_mtime("abc", NOW, NOW), None)

# 优先级
meta = {"creation_time": "2026-11-01T06:00:00Z"}
check("优先级 元数据优先", rt.detect(None, "20261103_143022.m4a", None, DUBAI, NOW, tags=meta), (local(2026, 11, 1, 10, 0), "metadata"))
check("优先级 其次文件名", rt.detect(None, "20261103_143022.m4a", str(int(local(2026, 11, 2) * 1000)), DUBAI, NOW, tags={}), (local(2026, 11, 3, 14, 30, 22), "filename"))
check("优先级 最后修改时间", rt.detect(None, "新录音.m4a", str(int(local(2026, 11, 2) * 1000)), DUBAI, NOW, tags={}), (local(2026, 11, 2), "file_mtime"))
check("全部未知", rt.detect(None, "新录音.m4a", None, DUBAI, NOW, tags={}), (None, ""))

INFO = """Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'a.m4a':
  Metadata:
    major_brand     : M4A
    creation_time   : 2026-11-03T10:30:22.000000Z
    comment         : a: b
  Duration: 00:00:01.00, start: 0.000000, bitrate: 79 kb/s
  Stream #0:0[0x1](und): Audio: aac (LC)
    Metadata:
      creation_time   : 1999-01-01T00:00:00Z
"""
check("ffmpeg 信息解析", rt.parse_ffmpeg_info(INFO), {"major_brand": "M4A", "creation_time": "2026-11-03T10:30:22.000000Z", "comment": "a: b"})
if shutil.which("ffmpeg"):
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "a.m4a"
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=1", "-c:a", "aac",
                        "-metadata", "creation_time=2026-11-03T10:30:22Z", str(target)], check=True)
        check("真实 m4a 元数据", rt.detect(target, "x.m4a", None, DUBAI)[1], "metadata")
        plain = Path(tmp) / "b.wav"
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=1", "-fflags", "+bitexact", str(plain)], check=True)
        check("无元数据 wav 回落文件名", rt.detect(plain, "20261103_143022.wav", None, DUBAI)[1], "filename")
        check("非音频文件不报错", rt.detect(Path(tmp) / "missing.bin", "x", None, DUBAI), (None, ""))
else:
    print("SKIP 本机无 ffmpeg，跳过真实文件元数据检查")

print("%d checks passed" % passed)
