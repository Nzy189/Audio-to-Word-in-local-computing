# Shengjian (声笺)

**English** | [简体中文](README.md)

> Upload an existing audio recording and get its transcript. The NAS web app accepts
> the file, and the job automatically prefers the LAN Windows RTX 5080 (FunASR CUDA);
> when the PC is off or unavailable it falls back to the NAS CPU (sherpa-onnx).
> Single user on a home LAN — no key of any kind between NAS and PC.

> **Note on language.** The web UI, logs and user-facing docs are written in Chinese.
> This English README documents the design; it does not mean the app emits English.

Development progress, deployment evidence and next steps live in
[PROJECT_STATUS.md](PROJECT_STATUS.md) (Chinese); this file is the project entrypoint.

---

## How it works

```text
Phone uploads an existing recording
    → NAS web app receives and persists the job
    → Automatically probes the PC transcription service
         ├─ PC on: over LAN → Windows FunASR / RTX 5080 → result back to the NAS
         └─ Off / busy / failed: local sherpa-onnx CPU, with the reason logged
    → Saves text, device, timing and per-task logs
    → Cleans up recordings and temp files on both sides
```

## Features

- Upload existing audio files (MP3 / M4A / WAV / WebM, …), up to 300 MB and 3 hours each; no microphone capture, no live transcription.
- Zero configuration: the default PC address is built in; whenever the PC is on, jobs use the GPU. The web "PC acceleration" card shows live online/offline status.
- Automatic fallback: PC off, asleep, busy, low on VRAM or failing → NAS CPU, with the exact reason in the task log.
- Job history: audio duration, processing time, submit/start/finish times, actual device and engine; click through to the full text, copy or download as TXT.
- Termination: queued, NAS CPU and PC GPU jobs can all be cancelled; the terminal state only appears after both sides' temp audio is cleaned.
- Auto-detects Chinese, English, Cantonese, Japanese and Korean; transcripts retained for 7 days.

## Install & run

- **Z2 Pro NAS (ARM64)**: see [deploy/nas/README.md](deploy/nas/README.md) (Chinese). Import the image, keep the existing `/data` mount and access code — no PC configuration file needed.
- **Windows GPU service**: see [worker/README.md](worker/README.md) (Chinese). Reuses an existing FunASR environment; auto-starts after Windows login.

## Layout

| Path | Role |
| --- | --- |
| `service/` | NAS-side FastAPI app: upload, scheduling, local CPU transcription, web UI, task logs |
| `worker/` | Windows-side FunASR CUDA service: single-job GPU transcription, cancellation, cleanup |
| `deploy/nas/` | ARM64 image, Compose, install guide and QA test scripts |
| `deploy/` (rest) | Legacy ECS deployment and ops files |
| `PROJECT_STATUS.md` | Master status document: progress, verification, addresses, secret locations, next steps |

Current version: 1.4 (keyless PC acceleration). Built release packages live in the local `dist/` folder and are not committed; actual deployment state is tracked in PROJECT_STATUS.md.
