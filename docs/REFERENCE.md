# 声笺：参考手册（需求、环境、架构、配置、运维、踩坑）

> **本文件按需查阅**：既定需求、地址与环境、架构、发布物与文件地图、凭据位置、任务生命周期、测试入口、运维速查、踩坑清单。
> 当前进度、下一步、验证状态与已知限制在 `PROJECT_STATUS.md`——开工先读那份。
> 更新日期：2026-10-28。本文件不含任何口令、密钥或用户转写内容。

## 1. 用户已经确定的需求

- 手机上传**已有音频文件**，录完再转写。不是实时字幕，不调用麦克风，不开发手机 App。
- 网页提供任务记录、录音时长、处理耗时、提交/开始/完成时间；点击记录查看具体结果，支持复制、TXT 下载和删除。
- 极空间 Z2 Pro 常开。电脑可用时优先使用 Windows RTX 5080；电脑关机、休眠、服务未就绪、忙碌、出错或中断时自动改用 NAS CPU。
- **内网单人使用：NAS 与电脑之间不需要任何密钥校验（2026-10-25 用户确定）。** 电脑开机即默认用电脑转写，网页只显示电脑在线/离线状态；只有电脑 IP 变化时才需要改地址。
- **NAS 与电脑的音频通信优先走局域网，不走 Tailscale。** 手机在外访问 NAS 可以继续用 Tailscale。
- 处理完成后删除两端录音与临时文件；失败与终止也要清理。电脑离线时，其残留只能在下次服务启动时清理，不能声称已经远程删除。
- 日志必须说明任务名、开始时间、实际设备/引擎，尤其是为什么没有使用电脑。不能只输出“引擎就绪”。
- 用户不熟悉远程环境变量，不应要求其手动填写 URL/token。当前版本（1.4 起）**无需密钥、无需导入电脑配置文件**；网页自动检测电脑状态，电脑 IP 改变时在网页修改地址即可。
- 用户提出暂停或终止；当前实现**终止**，没有实现暂停/断点恢复。
- 保留已有转写记录，不中断或清空用户正在运行的业务。

当前产品限制：单文件 300 MB、最长 3 小时，最多 10 个未结束任务，NAS 按任务逐条处理。文字记录保留 7 天，持有同一网页口令的人共用一个空间。

## 2. 地址、设备与运行环境

| 用途 | 地址 / 位置 | 说明 |
| --- | --- | --- |
| NAS 局域网网页 | `http://192.168.1.66:18088` | 已核查可访问 |
| NAS Tailscale 网页 | `http://100.114.153.9:18088` | 已核查可访问 |
| NAS 容器端口 | `8787/TCP` | 宿主机端口是 18088，不是 18080/18081 |
| 电脑 GPU HTTP 服务 | `http://192.168.1.73:18788` | 后台 API，不是手机网页；1.4 起内网单人使用、无密钥 |
| 电脑 Tailscale 地址 | `100.100.170.72` | 不作为当前音频传输目标 |
| ECS 网页 | `https://80.238.236.1` | 80/443 是网关，应用监听 127.0.0.1:8787 |
| ECS SSH | `80.238.236.1:22`，用户 `root` | 凭据未写入本文件 |

**端口经过用户纠正：18080 被其他程序占用，18081 只是曾经建议，实际使用并核查成功的是 18088。** 不要修改其他程序或再次推荐占用 18080。

### NAS

- 极空间 Z2 Pro，RK3568、四核 Cortex-A55 2 GHz、4 GB 内存，ARM64。
- 当前镜像目标是 `linux/arm64`，不能直接使用 ECS 的 x86 镜像。
- 容器建议先限制为 2 核、2 GB；这不是已测得的实机峰值保证。
- NAS 上实际数据文件夹的宿主机路径**尚未记录**。升级前从容器挂载设置确认，不能猜一个新目录。
- 没有取得 NAS 的 SSH 管理账号/凭据。已有网页口令不等于 NAS SSH 密码；不能据此声称可以直接登录宿主机部署。

### Windows 电脑

- 主机名 CANAL，Windows 11；AMD Ryzen 9 9950X3D，NVIDIA RTX 5080，约 16 GB 显存。
- 曾核查 NVIDIA 驱动 617.42、GPU compute capability 12.0。
- 复用用户现有环境：`F:\Claude Code Project\DeepTutor\FunASR\.venv`。
- FunASR 为 editable 安装，实际源码在 `F:\Claude Code Project\DeepTutor\FunASR\funasr\`，不要假定 `site-packages/funasr/` 一定存在。GPU worker 当前源码动态批次预算 `batch_size_s=300`（由 60 调高，按分段时长/补齐成本组批，并非文件个数），一次一个任务，保留 FP32；`merge_length_s=15`、VAD 最长片段 30 秒，PyTorch CPU 线程 4。`/v1/health` 返回 batch_size_s 与模型参数实际 precision，启动日志也记录这些值。参数需在空闲时重启后才生效，历史安装包不随源码更新。性能评估须看负载期耗时与峰值显存，空闲 nvidia-smi 不能证明是否跑满。
- 已核查版本：Python 3.12.13、PyTorch 2.11.0+cu128、torchaudio 2.11.0+cu128、FunASR 1.4.16。
- GPU 服务采用标准库 HTTP 服务，不需要向原 FunASR 虚拟环境追加 FastAPI/Uvicorn，未修改原 FunASR 仓库代码或重装其依赖。
- FFmpeg 使用现有 WinGet 安装的 `ffmpeg-9.0.2-full_build`。`worker/server.py` 会自动查找完整路径，不依赖交互终端先激活或追加 PATH。
- 系统全局 Python 位于 `C:\Python314\python.exe`，用于工具/测试脚本，**不是 GPU 服务的 Python**。
- 已读取以太网 MAC：`BC-FC-E7-B3-32-0F`，可用于路由器 DHCP 保留。

模型缓存已存在于：

```text
C:\Users\nzy189\.cache\modelscope\models\iic--SenseVoiceSmall\snapshots\master
C:\Users\nzy189\.cache\modelscope\models\iic--speech_fsmn_vad_zh-cn-16k-common-pytorch\snapshots\master
```

### ECS

- CentOS 7、3.10 内核、4 vCPU、约 15 GB 可用规格内存，无 GPU。
- 为兼容旧内核，安装了 Docker 静态版 26.1.4；没有升级宿主系统。
- 容器运行时在 `/opt/atow/runtime/docker/`，systemd 服务为 `atow-docker.service`。
- 使用 host 网络、关闭 Docker 自动桥接/iptables 修改。Nginx 对外，应用只在 loopback 监听。
- 采用 IP HTTPS 证书，`atow-renew.timer` 每 12 小时检查续期，成功后重载 Nginx。最初签发证书有效期很短，后续需以实际证书/续期日志为准。

## 3. 架构与识别引擎

```text
手机已有录音
    → NAS 网页上传 / 持久化任务
    → 读取当前电脑连接设置并检测服务
         ├─ 可用：LAN → Windows FunASR / RTX 5080 → 结果回到 NAS
    → 转写完成后（LLM 已配置时）AI 提炼：优化正文 + 分类概要（SSE 流式，原始转写永久保留）
    → 保存文字、设备/引擎、耗时和任务日志
    → 清理录音与临时文件
```

| 执行位置 | 引擎 | 模型 / 运行方式 |
| --- | --- | --- |
| ECS 1.5.9 CPU | `SenseVoice FP32 / sherpa-onnx CPU` | ONNX FP32 模型 + Silero VAD；16 kHz 单声道转换、分段识别，模型外置挂载 |
| NAS 已发布版本 / 旧 ECS CPU | `SenseVoice INT8 / sherpa-onnx CPU` | 原 ONNX INT8 模型 + Silero VAD；NAS FP32 镜像尚未构建 |
| Windows GPU | `SenseVoiceSmall / FunASR CUDA` | 现有 FunASR + PyTorch CUDA + FSMN VAD，明确验证模型参数在 CUDA 上 |
| NAS（AI 提炼） | OpenAI 兼容 API（默认百炼专属端点 + kimi-k3） | SSE 流式；不发送 temperature（推理模型拒绝）；进度与 ETA 写容器日志 |

不要把“有 5080”当成已经调用 GPU 的证据。应看任务 `backend`、`backend_name`、`engine_name`、`worker_note` 与日志。电脑健康服务就绪只是前提，NAS 还必须保存正确的连接配置。

GPU 服务一次处理一个任务；未就绪、忙碌或空闲显存不足时 NAS 会回退。当前检查的空闲显存阈值约 1.5 GiB。远程任务默认最多等待 900 秒，超过后回退；不会自动唤醒电脑。

## 4. 发布物与文件地图

### 最新发布物

**ECS 1.6.1：** 镜像 `atow-transcriber:1.6.1-ecs`，ID 前缀 `7284a25d34f9`，基于已部署的 1.6.0 复用依赖构建。源码包 `dist/shengjian-1.6.1-ecs/source.tgz`，30,016 字节，SHA-256 `0a21bc4790c19c2e715804cb9a89437ee6104400aac0a7764c493d2d89c86327`；服务器发布目录 `/opt/atow/releases/1.6.1-ecs/`，未导出本地镜像 tar。部署授权及验证见主状态文档。

**ECS 1.6.0**：

- 镜像 `atow-transcriber:1.6.0-ecs`，ID 前缀 `b01037c9d7fe`；在 ECS 用 `deploy/ecs/Dockerfile.upgrade` 并指定 `BASE_IMAGE=atow-transcriber:1.5.9-ecs` 复用原依赖构建，模型继续使用原 FP32 挂载。
- 本地源码包 `dist/shengjian-1.6.0-ecs/source.tgz`，SHA-256 `aef3b8c2f32deed242f161da48c0dce536157a41bac481e38f6415cce594d97f`；附 BUILD-INFO.json、DEPLOYMENT.json。服务器目录 `/opt/atow/releases/1.6.0-ecs/`，未导出新版本地镜像 tar。包中无凭据、模型或用户数据。
- 启动模板 `deploy/start-app.sh` 默认镜像为 1.6.0；保留 `/opt/atow/data`、模型、app.env 与原资源/安全限制。1.6.0 在原库增加七列，旧完成提炼回填 corrected_status=done；旧硬件信息不补造。

**ECS 1.5.9 FP32**：

- 镜像 `atow-transcriber:1.5.9-ecs`，ID 前缀 `12f262fb8831`，在 ECS 基于 `atow-transcriber:1.5.8-ecs` 复用依赖就地构建；Dockerfile 为 `deploy/ecs/Dockerfile.upgrade`。
- 源码包 `dist/shengjian-1.5.9-ecs/source.tgz`；SHA-256 `fcb6086fc7d90efab249269565f9b51e3ee653a6bcf63ef1969ed4b752809fa6`。服务器发布目录 `/opt/atow/releases/1.5.9-ecs/`，没有导出新版本地 Docker tar；部署结果见本地 DEPLOYMENT.json 与主状态文档。
- FP32 文件 `/opt/atow/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/model.onnx`，937,617,178 字节，SHA-256 `977016bd9c79f9eb343430b5cc305e07ab64d5212dff41b0dcfa1694bee9a8cb`。本地同名目录位于 `build-assets/models/`；tokens.txt 与 LICENSE 同目录，Silero VAD 继续放在模型根目录。
- 下载源为发布者公开仓库 `https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17`，校验信息来自仓库模型 API。使用 `python deploy/fetch-fp32.py --models-dir 模型根目录` 可下载并校验，只写入新目录，不覆盖原 INT8 文件。
- NAS 最新已发布包仍为下述 1.5.8，**没有 NAS FP32 新镜像或安装包**。新源码的 NAS Dockerfile 已改为只复制 FP32 目录及 VAD，后续构建前需完成资源评估与版本同步。

**ECS amd64 历史包** `dist/shengjian-1.5.8-ecs/`：

- 镜像归档 `atow-ecs-amd64.tar`：123,867,136 字节；SHA-256 `2aaba7e70a8999b609f86879559551bb4baec6a977784bf9e3fc3c30e4cd17d7`。
- 镜像标签 `atow-transcriber:1.5.8-ecs`；归档 manifest/config 已核对 `linux/amd64`。
- 附 `start-app.sh`、`README.md`、`BUILD-INFO.json`、`SHA256SUMS.txt`，不含凭据、模型或用户数据，模型继续复用服务器原挂载。是否已实际部署及当前版本以 PROJECT_STATUS.md 为准；BUILD-INFO 保留构建时信息。

**NAS ARM64** 发布目录 `dist/shengjian-1.5.8/`：

- ZIP：274,943,585 字节，约 262.2 MiB；SHA-256 `c6bf4a2f58bfaf25d5f698d0fb63782e18a0095c861ce15794a28850f3ff1ed8`。
- 镜像 tar：275,777,024 字节，SHA-256 `2a12728feeedf1b451e7e35b9f1fa8af5cca0fa61ff67f2e6ebe1a25526b2139`；镜像标签 `shengjian:1.5.8-arm64`，架构 arm64，验证容器实测 health 返回 `"version":"1.5.8"`。
- 包内：模型、VAD、FFmpeg；`nas.env` 含网页口令并附注释掉的 `LLM_*` 模板（Key 留空）；`windows-worker/server.py` 与当前 `worker/server.py` 逐字节一致；`SHA256SUMS.txt` 覆盖 13 个文件，`sha256sum -c` 全部 OK；ZIP 解压 14/14 与源一致。**不含任何 API Key，也无 `computer-connection.json`**，不要公开分享整个个人安装包。
- `dist/shengjian-1.5/` 至 `dist/shengjian-1.5.7/` 已被取代，仅作历史保留；更早的 1.1–1.4 发布包与 `atow-source.tgz` 同为历史参考，**不要当成当前源码**。

### 源码地图（以下路径相对于项目目录）

| 文件 / 目录 | 职责 |
| --- | --- |
| `service/app.py` | FastAPI、认证、SQLite、任务调度、本地 CPU、电脑地址设置（默认内置）、状态检测、事件日志、访问审计（未登录访问/登录尝试/退出，audit_log 表）、终止与清理、AI 提炼挂接与设置接口 |
| `service/llm_refine.py` | AI 提炼客户端：OpenAI 兼容 API 调用、Key 掩码、超时与重试、结果解析（优化正文 + 要点概要） |
| `service/remote_worker.py` | LAN 电脑客户端（无密钥）、分类型连接失败、流式发送、状态轮询、取消和结果确认 |
| `service/index.html` | 手机适配单页：上传、电脑在线状态显示、地址修改、AI 提炼设置卡、历史、详情（AI 内容/原文双页签）、日志、终止、下载 |
| `service/requirements.txt` | NAS/ECS Python 依赖版本固定 |
| `service/Dockerfile` | ECS 应用构建，监听 127.0.0.1:8787；不能直接代替 NAS Dockerfile |
| `deploy/nas/Dockerfile` | ARM64 NAS 镜像，内置模型、0.0.0.0:8787、健康检查、无 ANSI 色彩 |
| `deploy/nas/entrypoint.py` | 准备专用数据目录所有者，随后降为非 root 用户 |
| `deploy/nas/compose.yaml` | NAS 部署配置，18088 → 8787、原数据目录、资源限制 |
| `deploy/nas/README.md` | 当前 NAS 用户安装/升级步骤；开发进度以 PROJECT_STATUS.md 为准 |
| `deploy/nas/stub-llm.py` | QA 用容器内 stub OpenAI 兼容服务（SSE），不是产品组件 |
| `deploy/nas/verify-refine.py` | AI 提炼两阶段容器验证脚本 |
| `deploy/nas/browser-refine-check.cjs` | 提炼浏览器 QA 脚本 |
| `tests/test_llm_refine.py` | 提炼客户端单测（当前 12 项检查） |
| `worker/server.py` | 原生 Windows HTTP GPU 服务、模型与 VAD、任务取消、临时文件清理 |
| `worker/start-worker.ps1` | 隐藏窗口启动，检测 18788 避免重复启动 |
| `worker/install-startup.ps1` | 当前用户登录自启快捷方式 |
| `worker/allow-lan-firewall.ps1`、`allow-nas.cmd` | Windows LAN 入站规则，需管理员；已由用户执行 |
| `deploy/start-app.sh`、`start-web.sh` | 原 ECS 容器启动脚本，不能与 NAS 配置混淆 |
| `deploy/ecs/README.md` | 当前 ECS amd64 镜像、保留原数据的升级与回滚顺序 |
| `deploy/ecs/run-qa.py`、`verify-smoke.py` | 隔离 ECS 镜像 QA：随机容器与 tmpfs、旧库迁移、CPU 转写、stub AI 提炼与下载；不操作生产 |
| `deploy/ecs/Dockerfile.upgrade` | 复用已部署镜像依赖，只复制应用源码；1.6.0 部署显式指定 BASE_IMAGE=atow-transcriber:1.5.9-ecs |
| `deploy/ecs/check-preservation.py` | 迁移前后比较既有记录字段、settings 和会话文件摘要；仅保存摘要与记录 ID，不输出原文或凭据；以数据库所属 UID 运行 |
| `deploy/fetch-fp32.py` | 下载 FP32 模型、断线续传、文件大小/SHA-256 校验；保留 INT8 原目录 |
| `deploy/atow-*.service`、`*.timer` | ECS 运行时与 HTTPS 续期 |
| `build-assets/models/` | 构建用模型文件，已忽略，不是业务录音 |
| `test-results/` | 公开样例与测试截图，已忽略，不打入镜像 |
| `dist/` | 已忽略的发布文件；ECS 源码包当前 1.6.1，NAS 最新安装包 1.5.8 |

## 5. 配置、凭据与持久化

本文件不保存任何口令或连接密钥明文。接续工作应从下面的位置按需读取，避免打印到日志、命令行参数或文档。

| 数据 | 存放位置 | 说明 |
| --- | --- | --- |
| NAS 网页访问口令 | 当前容器 `ACCESS_CODE`；个人发布目录 `nas.env` | 手动创建容器不会自动加载该文件，仍需填写这一个必填变量 |
| AI 提炼 API Key | `nas.env` 的 `LLM_API_KEY`（初始默认）或 `/data/jobs.sqlite3` 的 `settings` 表（网页“AI 提炼设置”保存后覆盖 env） | 不写入文档；网页与接口只显示掩码；无 Key 时提炼自动关闭，转写不受影响 |
| PC 服务连接密钥 | **1.4 起不再使用**；即使旧配置仍有 `WORKER_TOKEN`，当前代码也不读取 | 无需填写或恢复；旧版本文件可能仍有历史字段 |
| NAS 电脑地址设置 | `/data/jobs.sqlite3` 的 `settings` 表（1.4 起仅存地址与开关，不再存密钥） | 默认地址 `http://192.168.1.73:18788` 已内置，无需导入任何文件 |
| NAS 会话签名密钥 | `/data/.session-secret` | 自动生成并持久化，权限 0600；升级/备份时保留 |
| ECS 应用凭据 | `/opt/atow/app.env` | root 只读权限 0600；并不包含 SSH 密码 |
| ECS SSH 登录密码 | 未写入项目文档 | 不能把网页口令拿去当 SSH 密码 |

旧参数 `REMOTE_WORKER_URL` 仍兼容（作为默认地址覆盖）；`REMOTE_WORKER_TOKEN` 在 1.4 起不再使用。1.5 新增 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` / `LLM_ENABLED` 环境变量（仅作初始默认值，默认百炼专属端点 + kimi-k3），网页“AI 提炼设置”保存后随时覆盖。

NAS 内部的数据包括：

```text
/data/jobs.sqlite3       jobs / settings / job_events
/data/.session-secret   会话签名密钥
/data/<任务ID>.upload    待处理的原录音，终态清理
/data/<任务ID>.wav       本机转换文件，终态清理
```

备份 SQLite 时，停止应用后复制整个数据目录，或使用 SQLite 在线备份，注意 WAL；不要只复制一个正在写入的 `.sqlite3` 文件。

NAS 默认以 UID/GID 10001 运行，入口会修改**挂载目录自身**的所有者。必须使用专用数据文件夹，不能挂 NAS 共享根目录或其他业务目录。支持非零 `PUID`、`PGID`。

## 6. 任务、终止、日志与文件生命周期

正常状态：

```text
queued → converting → processing → done / error
queued → remote_upload → remote_processing → done
远程失败 → converting → processing → done / error
```

终止状态：

```text
任意未完成任务 → cancelling（终止中）→ cancelled（已终止）
排队任务可直接完成取消。
```

- CPU：终止转换子进程，在 VAD/识别分段边界检查取消信号。当前原生识别调用需要短暂结束，不保证点击瞬间停下。
- GPU：NAS 通知电脑；电脑在 PyTorch ASR/VAD 模块边界抛出取消信号，等待已提交运算结束，清理录音。不会只删文件却让后台整段继续识别。
- NAS 在本地音频清理、终止事件写入后才显示 `cancelled`。清理失败保留 `cancelling`，后台重试。
- 电脑离线无法当场清理其磁盘，NAS 会注明，电脑服务下次启动处理残留。
- 取消不应触发“再用 NAS 重转”；远程断线与取消同时发生的竞争已有专门测试。
- `cancelling` 在重启后继续清理，不恢复转写；普通处理中任务重启后重新排队，从头处理，不是断点恢复。
- AI 提炼状态：`none / running / done / failed`；容器重启会把残留 `running` 复位为 `failed` 并提示重新提炼（1.5.6 起）。提炼失败不影响转写结果。
- 已终止任务保留日志和记录，允许用户再删除。已完成/失败/终止记录按 7 天保留策略处理。
- 取消会清空部分文字，防止误把不完整输出当成完成结果。

清理策略：NAS 保留原录音直到远程结果成功保存，或本机结束/终止，再删除；PC 结束或失败就删除原文件和 WAV，NAS 确认后删除 PC 结果元数据。未确认的 PC 文字元数据最多留一小时，音频已提前清理。

容器日志与网页 `job_events` 含任务名、开始时间、实际设备/引擎、调度原因、完成耗时、终止和清理；AI 提炼全程有时间线（开始/每 30 秒进度与 ETA/完成或失败）。应用日志使用显式 `+04:00`，NAS 日志界面的外层时间可能按 NAS 自身时区显示；网页按设备时区。旧记录不补造历史耗时、引擎或日志。

## 7. 测试入口与测试边界

| 文件 | 目标 / 说明 |
| --- | --- |
| `deploy/verify.py` | 原 ECS 环境，读取服务器应用配置；会创建并清理测试任务 |
| `deploy/browser-check.cjs`、`records-check.cjs` | 历史 ECS 浏览器与记录测试 |
| `deploy/migration-check.py` | 在镜像内运行，隔离临时 SQLite，不启动真实识别 worker |
| `deploy/nas/verify-arm64.py` | 早期 1.1 ARM64 测试，有旧镜像/容器名，不应直接当当前版本入口 |
| `deploy/nas/verify-hybrid.py`、`fault-worker.py` | 1.2 混合调度和故障模拟，需要隔离 QA 容器 |
| `deploy/nas/verify-observability.py` | 零配置直连、网页地址设置、具体失败原因、日志、实际 GPU 与重启 |
| `deploy/nas/verify-cancellation.py` | 排队/本机/实际 GPU 终止与音频清理，使用公开合成的一小时 WAV |
| `deploy/nas/verify-cancel-race.py` | 取消与断线竞争、重启恢复，隔离临时数据库 |
| `deploy/nas/browser-settings-check.cjs` | 无导入/无密钥状态卡、任务日志、终止、下载与手机 QA；会重置隔离 QA 的设置 |
| `deploy/nas/stub-llm.py` | QA 用容器内 stub OpenAI 兼容服务（按 system prompt 分纪要/净化两相，末块附 usage；按 model 名分流 500/延迟/净化失败，SSE 协议），不是产品组件 |
| `deploy/nas/verify-refine.py` | AI 提炼容器验证（`a`：无 env 默认与旧库迁移；`b`：stub 全链路，含两段时序、净化单独重试与双 409），需要隔离 QA 容器 |
| `deploy/nas/browser-refine-check.cjs` | AI 设置卡、双页签、两段渲染与 usage 行、识别硬件行、概要复制/下载与手机 QA；会重置隔离 QA 的设置 |
| `tests/test_llm_refine.py` | 提炼客户端单测（18 项：两相纯文本、usage 实测/估算、切段并行、段失败/重试、SSE 错误、进度与 ETA） |
| `deploy/ecs/run-qa.py` | 本地 ECS amd64 镜像 QA，创建随机名容器与 tmpfs 并自动清理；不可改为生产容器 |

**不要把测试脚本中的 QA 容器名改成用户的生产容器直接执行。** 测试会上传/删除任务，部分还会重启容器、清空 QA 连接设置。应先阅读脚本中的固定端口、名称、路径和测试前置条件。

用户提供的性能基准：`c9.xlarge.4`，4 核 16 GB：1 小时 52 分钟（6720 秒）音频，耗时 2 分 54 秒（174 秒）。约 38.6 倍实时速度，RTF 约 0.026。这是用户实测，不能用于推算 Z2 Pro、不同模型或 GPU 的同音频耗时。

## 8. 运维与重建速查

### 检查 NAS 版本

```powershell
Invoke-RestMethod 'http://192.168.1.66:18088/api/health'
```

应返回 `version: 1.5.8`（物理 NAS 升级前仍返回旧版本；网页右上角状态区下也直接显示 v1.5.8）。健康接口显示 ready 不等于电脑加速已经连通；后者看网页“电脑加速”状态卡。

### 检查电脑 GPU 服务

电脑服务不需要密钥。可用以下请求检查当前状态：

```powershell
Invoke-RestMethod 'http://192.168.1.73:18788/v1/health'
```

应返回 `ready`、`busy`、`name`（RTX 5080）。若返回 401/403，检查目标地址是否正确、是否仍有旧版服务或访问代理；不要为当前新版重新配置密钥。

### Windows 运行位置

- 日志和暂存目录：`C:\Users\nzy189\AppData\Local\ShengjianWorker`。
- 自启快捷方式：当前用户 Startup 中的 `Shengjian GPU Worker.lnk`。
- 快捷方式目标：原 FunASR 的 `.venv\Scripts\pythonw.exe`。
- 参数：项目 `worker/server.py --config worker/worker.env` 的绝对路径。
- 手动启动：`worker/start-worker.ps1`。当前已运行时不要启动重复实例。
- 重启前先查健康接口 busy，等待当前任务结束；仅操作确认命令行指向本项目的进程，不要按 python 进程名批量终止。

### 重建 ARM64 镜像

在 `F:\Codex Project\atow`：

```powershell
docker buildx build --platform linux/arm64 --load --provenance=false `
  --tag shengjian:1.5.8-arm64 --file deploy/nas/Dockerfile .

docker buildx build --platform linux/arm64 --provenance=false `
  --tag shengjian:1.5.8-arm64 --file deploy/nas/Dockerfile `
  --output type=docker,dest=dist/shengjian-1.5.8/shengjian-z2pro-arm64.tar .
```

需要 Docker Desktop 的 Linux 引擎运行，已核查支持 ARM64 模拟。NAS 构建上下文是项目根目录。`build-assets/models/` 必须存在；其内容为 SenseVoice INT8 模型、tokens、许可证和 Silero VAD。

升级版本时同步镜像标签、`compose.yaml`、`app.py` 健康接口版本、发布目录和 BUILD-INFO。导出使用 `type=docker`、关闭 provenance，避免把仅适合新引擎的归档格式交给旧 NAS。

打 ZIP 前同步用户 README、Compose、Windows 文件；1.4 起不再生成或包含 `computer-connection.json`，`windows-worker/worker.env` 为无密钥的注释模板。1.5 起 `nas.env` 另附注释掉的 `LLM_*` 模板行（Key 留空，不写入任何真实 Key）。重算 `SHA256SUMS.txt`，验证镜像 manifest/架构和 ZIP 完整性。文档摘要校验值随实际发布物更新，已发布的包不要仅因文档整理而重写。

### ECS 运维（仅在需要处理 ECS 时）

```sh
systemctl status atow-docker --no-pager
/opt/atow/runtime/docker/docker ps
/opt/atow/runtime/docker/docker logs --tail 100 atow-app
systemctl list-timers atow-renew.timer --no-pager
journalctl -u atow-renew.service --no-pager -n 50
```

ECS 原启动/网关/证书文件均在 `/opt/atow`，主要容器为 `atow-app`、`atow-web`。不要为处理 NAS 问题顺手覆盖 ECS 生产服务，也不要在原 CentOS 7 上安装不兼容的新运行时。

修改 ECS 网页口令时，只更新受保护的 `/opt/atow/app.env` 中 ACCESS_CODE，不修改 SSH 密码。环境变量更新必须以同一镜像重建应用容器，仅 `docker restart` 不会重读 env 文件。操作前确认转写和 AI 提炼均空闲，备份原配置及容器信息到服务器 0700 目录（凭据文件 0600），继续使用原数据、模型挂载及其余环境设置。新口令通过隐藏输入传入，不放入命令参数、日志或文档；完成后只确认健康状态和新口令登录。原会话签名配置保持原样，已有登录会话继续有效。

## 9. 已遇到的问题和应避免重复的误判

| 问题 | 已定位原因 / 处理 |
| --- | --- |
| 容器启动提示 `Set ACCESS_CODE...` | 手动创建未设置网页口令，镜像不会自动读取旁边的 nas.env；当前版本仍需这个网页口令，与已删除的电脑连接密钥无关 |
| 网页端口冲突或访问不到 | 18080 被占用；用户实际选了 18088。不要再拿旧建议 18081 做检查 |
| GPU 0%，NAS 在跑，电脑明明开机 | 当时 PC 健康 ready，NAS 任务直接 local_cpu 且 worker_note 为空，说明 1.2 没有启用远程配置；用户明确说没有填写那两个变量 |
| 用户不理解 URL/token | 当前版本（1.4 起）已删除电脑连接密钥校验并内置默认地址，无需导入配置；网页自动检测状态，仅在 IP 改变时修改地址，回退原因写入日志 |
| 日志只有引擎就绪且有 `[32m` 乱码 | 已加入逐任务日志，Uvicorn 使用 `--no-use-colors` |
| PC 保存结果时 WinError 17 | 曾在同目录 `os.replace` 出错，已对 Windows 错误 17 做 copy+unlink 兼容；具体文件系统原因未进一步确认，不要随意移除该兼容处理 |
| Docker 向 readonly/tmpfs 的 `/tmp` 复制测试文件失败 | 改用 `docker exec -i` 将测试字节写入临时文件，不能据此判断业务上传失败 |
| `docker exec` 用 root 打开 SQLite 失败 | 容器去掉了 DAC_OVERRIDE，数据库属 UID 10001；需要 `--user 10001:10001`，不要盲目放宽权限 |
| Playwright 大文件 Buffer 超过 50 MB | 测试应向 `setInputFiles` 传实际文件路径；不是产品上传上限变成 50 MB |
| CPU/GPU 取消过程中竞争 | 区分 TaskCancelled 与远程失败；不要把取消重新送去 CPU。终态在清理和终止事件保存后提交 |
| kimi-k3/qwen3.8-max 提炼报 HTTP 400 | 推理模型拒绝 `temperature` 参数；1.5.2 起请求不再发送该参数，勿再加回 |
| 长录音提炼报 read operation timed out | 非流式请求下服务器全部生成完才发首字节，超过 120 秒读取超时；1.5.2 起改 SSE 流式，勿改回非流式 |
| 重新提炼按钮消失、重试永远 409 | 容器在提炼中重启致 refine_status 永久 running；1.5.6 起启动自动复位。提醒用户勿在提炼中重启容器 |
