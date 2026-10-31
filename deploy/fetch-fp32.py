"""Download the published SenseVoice FP32 model, with size/hash verification.

Writes only a new model directory; existing INT8 files remain available for rollback.
"""
import argparse
import hashlib
from pathlib import Path
import shutil
import time
import urllib.request

NAME = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
SOURCE = "https://huggingface.co/csukuangfj/" + NAME + "/resolve/main/"
SIZE = 937617178
SHA256 = "977016bd9c79f9eb343430b5cc305e07ab64d5212dff41b0dcfa1694bee9a8cb"


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def fetch_model(target):
    if target.exists():
        if target.stat().st_size != SIZE or digest(target) != SHA256:
            raise SystemExit("Existing FP32 file has an unexpected hash; leaving it untouched")
        print("FP32 model already present; SHA-256 verified", flush=True)
        return
    partial = target.with_suffix(".onnx.part")
    for attempt in range(3):
        offset = partial.stat().st_size if partial.exists() else 0
        if offset == SIZE:
            break
        if offset > SIZE:
            raise SystemExit("Partial model is larger than the expected file")
        headers = {"User-Agent": "Shengjian-model-fetch/1.6.0"}
        if offset:
            headers["Range"] = "bytes=" + str(offset) + "-"
        try:
            request = urllib.request.Request(SOURCE + "model.onnx", headers=headers)
            with urllib.request.urlopen(request, timeout=60) as response:
                append = response.status == 206 and offset > 0
                if not append:
                    offset = 0
                last_report = time.monotonic()
                with partial.open("ab" if append else "wb") as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
                        offset += len(chunk)
                        if time.monotonic() - last_report >= 10:
                            print("FP32 download: %.1f%%" % (100 * offset / SIZE), flush=True)
                            last_report = time.monotonic()
            break
        except OSError as exc:
            if attempt == 2:
                raise
            print("Download interrupted; resuming (%s)" % type(exc).__name__, flush=True)
    if partial.stat().st_size != SIZE or digest(partial) != SHA256:
        raise SystemExit("FP32 size/hash mismatch; model was not activated")
    partial.replace(target)
    print("FP32 model downloaded; size and SHA-256 verified", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models-dir", type=Path, default=Path("build-assets/models"))
    root = parser.parse_args().models_dir
    target = root / NAME
    target.mkdir(parents=True, exist_ok=True)
    fetch_model(target / "model.onnx")
    with urllib.request.urlopen(SOURCE + "tokens.txt", timeout=60) as response:
        tokens = response.read(1024 * 1024)
    if len(tokens) != 315894:
        raise SystemExit("Unexpected token file size")
    (target / "tokens.txt").write_bytes(tokens)
    old_license = root / NAME.replace("-2024", "-int8-2024") / "LICENSE"
    if old_license.exists():
        shutil.copyfile(old_license, target / "LICENSE")
    (target / "README.md").write_text(
        "SenseVoiceSmall FP32 ONNX model\nSource: " + SOURCE + "model.onnx\nSHA-256: " + SHA256 + "\n",
        encoding="utf-8")
    print("Model assets ready: " + str(target), flush=True)


if __name__ == "__main__":
    main()
