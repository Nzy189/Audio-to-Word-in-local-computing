# 声笺：开发进展与工作接续手册

> **这是本项目唯一的开发状态主文档。后续继续开发、排障或部署，先读本文件。**
>
> 更新日期：2026-10-27，用户时区 Asia/Dubai（UTC+04:00）。
> 最近一次运行验证：**2026-10-28**，1.5.5 镜像 health 实测、结构化摘要真实端点验证与发布打包核验；各目标的最后确认状态见下表。本次未触碰生产容器、电脑 GPU 服务与物理 NAS。
> 项目目录：`F:\Codex Project\atow`。

## 1. 先看当前进度

**1.5（AI 提炼 + 识别调优）已构建、通过全部 QA 并交付安装包；电脑 GPU 服务仍运行 1.4 代码，1.5 调优需重启后才生效；物理 NAS 仍是旧版，待用户导入 1.5 镜像。**

**当前源码已删除 NAS↔电脑的连接密钥校验。** NAS 客户端不发送 Authorization，电脑服务不读取 `WORKER_TOKEN`，健康检查、上传、轮询和取消均无需连接密钥。网页无需导入 `computer-connection.json`，默认电脑地址已内置，只保留在线状态、GPU 优先开关与地址修改。NAS 网页的 `ACCESS_CODE` 登录口令和会话校验仍保留。下文 1.2/1.3 的密钥与导入流程仅为历史记录，不作为当前操作步骤。

**1.5 新增 AI 提炼与识别调优。** 转写完成后 NAS 端调用 OpenAI 兼容 API（默认百炼专属端点 + kimi-k3）生成优化正文与要点概要；`LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` / `LLM_ENABLED` 环境变量与网页“AI 提炼设置”卡片为双通道配置，网页保存的配置随时覆盖环境变量；详情页提供 AI 内容 / 原文双页签（默认 AI），提炼失败可重新提炼，**原始转写永远保留**。识别链路针对噪声录音调优：FFmpeg highpass/lowpass 滤镜、Silero VAD 0.6、FSMN `speech_noise_thres` 0.75；调优参数尚未经真实录音 A/B 验证。另修复网页首屏未登录 401 探测与 favicon 404 控制台报错。

| 对象 | 已完成 / 最后确认状态 | 仍需注意 |
| --- | --- | --- |
| 本地源码 | 1.5：AI 提炼（NAS 端 OpenAI 兼容 API、env+网页双通道、详情页双页签、随时一键生成/重新生成、摘要要求具体信息、错误详情透出、不发送 temperature）、识别链路降噪调优、网页首屏控制台报错修复；1.4 免密钥等其余功能保留 | 单测 10/10、容器 Phase A 3/3 + Phase B 7/7、浏览器 10/10、真实端点验证（kimi-k3 全形状 200 + 摘要具体性）、真实 GPU 回归 7+4 全部通过（2026-10-28） |
| 最新发布物 | `dist/shengjian-1.5.5.zip`；镜像 `shengjian:1.5.5-arm64` | 已构建、验证；**不含任何 API Key，也不含 computer-connection.json**；不能据此推断已安装到 NAS |
| Windows RTX 5080 服务 | **仍运行 1.4 代码**（2026-10-25 重启的免密钥版，实测通过）；1.5 调优需重启服务后生效 | 重启前先确认健康接口非 busy、进程命令行指向本项目；由控制器与用户协调执行，不要擅自操作 |
| Windows 防火墙 | `Shengjian-GPU-LAN-18788` 规则已启用，允许本地子网 TCP 18788 | 用户已实际执行管理员脚本，不要反复要求其再次放行 |
| 物理极空间 NAS | 用户已运行旧版；网页和健康接口均可访问；此前确认具有 1.2 混合版界面 | **未升级 1.5**；导入 1.5 前仍走 NAS CPU（1.2 从未配置电脑地址） |
| ECS | 网页健康检查正常；最后通过 SSH 部署的是转写记录版 `atow-transcriber:records-v2` | 后续 NAS 1.1～1.5 功能没有自动同步部署到 ECS |

### 下一步从这里继续

1. 重启电脑 GPU 服务到 1.5 代码（与用户确认后执行）：先查 `http://192.168.1.73:18788/v1/health` 确认非 `busy`，核对监听 18788 的进程命令行含 `worker\server.py` 再停止，用 `worker/start-worker.ps1` 重新启动并复核健康接口 ready。
2. 用户在极空间导入 `dist/shengjian-1.5.5/shengjian-z2pro-arm64.tar`（镜像 `shengjian:1.5.5-arm64`），**继续挂载原 `/data` 文件夹，保持 18088 → 8787，保留原 `ACCESS_CODE`**；无需再导入任何电脑配置文件。
3. 检查 NAS `http://192.168.1.66:18088/api/health` 返回 `"version":"1.5.5"`（旧包返回 1.5.4 或更早；网页右上角状态区下也会直接显示 v1.5.5）。
4. 配置 AI 提炼：在 NAS `nas.env` 取消注释 `LLM_API_KEY` 并填入 Key（包内模板已给出其余默认项），或登录网页在“AI 提炼设置”卡片中配置并测试连接；随后上传一段短录音，确认详情页默认显示 AI 内容页签、可切回原文、概要可复制/下载。
5. 用此前“噪声大”的真实录音做 A/B 对照验收（对照 1.4 时代的记录比较错别字、口水词、无意义输出）；若识别质量变差，按第 12 节单独回滚调优参数，不影响 AI 提炼功能。
6. 将结果和检查时间更新到本文件。**不要把 Docker Desktop ARM64 模拟验证写成 Z2 Pro 实机验证。**

## 2. 用户已经确定的需求

- 手机上传**已有音频文件**，录完再转写。不是实时字幕，不调用麦克风，不开发手机 App。
- 网页提供任务记录、录音时长、处理耗时、提交/开始/完成时间；点击记录查看具体结果，支持复制、TXT 下载和删除。
- 极空间 Z2 Pro 常开。电脑可用时优先使用 Windows RTX 5080；电脑关机、休眠、服务未就绪、忙碌、出错或中断时自动改用 NAS CPU。
- **内网单人使用：NAS 与电脑之间不需要任何密钥校验（2026-10-25 用户确定）。** 电脑开机即默认用电脑转写，网页只显示电脑在线/离线状态；只有电脑 IP 变化时才需要改地址。
- **NAS 与电脑的音频通信优先走局域网，不走 Tailscale。** 手机在外访问 NAS 可以继续用 Tailscale。
- 处理完成后删除两端录音与临时文件；失败与终止也要清理。电脑离线时，其残留只能在下次服务启动时清理，不能声称已经远程删除。
- 日志必须说明任务名、开始时间、实际设备/引擎，尤其是为什么没有使用电脑。不能只输出“引擎已就绪”。
- 用户不熟悉远程环境变量，不应要求其手动填写 URL/token。当前版本（1.4 起）**无需密钥、无需导入电脑配置文件**；网页自动检测电脑状态，电脑 IP 改变时在网页修改地址即可。1.3 的导入/测试流程已被替代。
- 用户提出暂停或终止；当前实现**终止**，没有实现暂停/断点恢复。
- 保留已有转写记录，不中断或清空用户正在运行的业务。

当前产品限制：单文件 300 MB、最长 3 小时，最多 10 个未结束任务，NAS 按任务逐条处理。文字记录保留 7 天，持有同一网页口令的人共用一个空间。

## 3. 地址、设备与运行环境

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

## 4. 架构与识别引擎

```text
手机已有录音
    → NAS 网页上传 / 持久化任务
    → 读取当前电脑连接设置并检测服务
         ├─ 可用：LAN → Windows FunASR / RTX 5080 → 结果回到 NAS
         └─ 不可用、失败、超时：NAS 本地 sherpa-onnx CPU
    → 保存文字、设备/引擎、耗时和任务日志
    → 清理录音与临时文件
```

| 执行位置 | 引擎 | 模型 / 运行方式 |
| --- | --- | --- |
| NAS / 原 ECS CPU | `SenseVoice INT8 / sherpa-onnx CPU` | ONNX INT8 模型 + Silero VAD，16 kHz 单声道转换，分段识别 |
| Windows GPU | `SenseVoiceSmall / FunASR CUDA` | 现有 FunASR + PyTorch CUDA + FSMN VAD，明确验证模型参数在 CUDA 上 |

不要把“有 5080”当成已经调用 GPU 的证据。应看任务 `backend`、`backend_name`、`engine_name`、`worker_note` 与日志。电脑健康服务就绪只是前提，NAS 还必须保存正确的连接配置。

GPU 服务一次处理一个任务；未就绪、忙碌或空闲显存不足时 NAS 会回退。当前检查的空闲显存阈值约 1.5 GiB。远程任务默认最多等待 900 秒，超过后回退；不会自动唤醒电脑。

## 5. 最新发布物与文件地图

### 最新 1.5 发布物

```text
F:\Codex Project\atow\dist\shengjian-1.5.5.zip
F:\Codex Project\atow\dist\shengjian-1.5.5\shengjian-z2pro-arm64.tar
F:\Codex Project\atow\dist\shengjian-1.5.5\nas.env
F:\Codex Project\atow\dist\shengjian-1.5.5\README.md
F:\Codex Project\atow\dist\shengjian-1.5.5\BUILD-INFO.json
F:\Codex Project\atow\dist\shengjian-1.5.5\SHA256SUMS.txt
```

- ZIP：274,944,230 字节，约 262.2 MiB；SHA-256 `52488798acb2b26fa5b6adcf03bf084ee778c52f431c892d0264228d9d6de469`。
- 镜像 tar：275,776,512 字节，SHA-256 `023c2b9789f0b3571c617cc9f19170777635dc7c4e0141d5357944f5a4956659`。
- 1.5.5 为最终交付版：在 1.5.4 基础上，摘要改为按大类分类组织并单列【遗留任务】（负责人+期限）。`dist/shengjian-1.5/` 至 `dist/shengjian-1.5.4/` 已被取代，仅作历史保留。
- Docker 镜像标签：`shengjian:1.5.5-arm64`；`docker image inspect` 确认架构 arm64；验证容器实测 `/api/health` 返回 `"version":"1.5.5"`。
- ZIP 解压核验：14/14 个文件与源目录一致，解压后 tar 的 SHA-256 与源一致。
- 镜像内包含模型、VAD、FFmpeg；不内置用户网页口令，也**不含任何 API Key**；包内无 `computer-connection.json`（免密钥后无需导入任何配置）。`nas.env` 含网页口令并附注释掉的 `LLM_*` 模板行（默认端点与 kimi-k3，Key 留空），不要公开分享整个个人安装包。
- `SHA256SUMS.txt` 覆盖包内 13 个文件（与 1.4 相同的文件集与格式），`sha256sum -c` 全部 OK。
- 包内 `windows-worker/server.py` 与当前 `worker/server.py` 逐字节一致（含 1.5 调优参数）。

旧发布物 `dist/shengjian-1.4.zip`（1.4）、`dist/shengjian-1.3.zip`（1.3）、`dist/shengjian-z2pro-arm64.zip`（1.1）、`dist/shengjian-hybrid-1.2.zip` 仅供历史参考。`atow-source.tgz` 也是较早的源码快照，**不要当成当前源码**。

### 源码地图（以下路径相对于项目目录）

| 文件 / 目录 | 职责 |
| --- | --- |
| `service/app.py` | FastAPI、认证、SQLite、任务调度、本地 CPU、电脑地址设置（默认内置）、状态检测、事件日志、终止与清理、AI 提炼挂接与设置接口 |
| `service/llm_refine.py` | AI 提炼客户端：OpenAI 兼容 API 调用、Key 掩码、超时与重试、结果解析（优化正文 + 要点概要） |
| `service/remote_worker.py` | LAN 电脑客户端（无密钥）、分类型连接失败、流式发送、状态轮询、取消和结果确认 |
| `service/index.html` | 手机适配单页：上传、电脑在线状态显示、地址修改、AI 提炼设置卡、历史、详情（AI 内容/原文双页签）、日志、终止、下载 |
| `service/requirements.txt` | NAS/ECS Python 依赖版本固定 |
| `service/Dockerfile` | ECS 应用构建，监听 127.0.0.1:8787；不能直接代替 NAS Dockerfile |
| `deploy/nas/Dockerfile` | ARM64 NAS 镜像，内置模型、0.0.0.0:8787、健康检查、无 ANSI 色彩 |
| `deploy/nas/entrypoint.py` | 准备专用数据目录所有者，随后降为非 root 用户 |
| `deploy/nas/compose.yaml` | NAS 部署配置，18088 → 8787、原数据目录、资源限制 |
| `deploy/nas/README.md` | 当前 NAS 用户安装/升级步骤；开发进度仍以本文件为准 |
| `deploy/nas/stub-llm.py` | 1.5 QA 用容器内 stub OpenAI 兼容服务，不是产品组件 |
| `deploy/nas/verify-refine.py` | 1.5 AI 提炼两阶段容器验证脚本 |
| `deploy/nas/browser-refine-check.cjs` | 1.5 提炼浏览器 QA 脚本 |
| `tests/test_llm_refine.py` | 提炼客户端单测（9 项检查） |
| `worker/server.py` | 原生 Windows HTTP GPU 服务、模型与 VAD、任务取消、临时文件清理 |
| `worker/start-worker.ps1` | 隐藏窗口启动，检测 18788 避免重复启动 |
| `worker/install-startup.ps1` | 当前用户登录自启快捷方式 |
| `worker/allow-lan-firewall.ps1`、`allow-nas.cmd` | Windows LAN 入站规则，需管理员；已由用户执行 |
| `deploy/start-app.sh`、`start-web.sh` | 原 ECS 容器启动脚本，不能与 NAS 配置混淆 |
| `deploy/atow-*.service`、`*.timer` | ECS 运行时与 HTTPS 续期 |
| `build-assets/models/` | 构建用模型文件，已忽略，不是业务录音 |
| `test-results/` | 公开样例与测试截图，已忽略，不打入镜像 |
| `dist/` | 历史/当前发布包，已忽略；最新是 1.5 |

## 6. 配置、凭据与持久化

本文件不保存任何口令或连接密钥明文。接续工作应从下面的位置按需读取，避免打印到日志、命令行参数或主文档。

| 数据 | 存放位置 | 说明 |
| --- | --- | --- |
| NAS 网页访问口令 | 当前容器 `ACCESS_CODE`；个人发布目录 `nas.env` | 手动创建容器不会自动加载该文件，仍需填写这一个必填变量 |
| AI 提炼 API Key | `nas.env` 的 `LLM_API_KEY`（初始默认）或 `/data/jobs.sqlite3` 的 `settings` 表（网页“AI 提炼设置”保存后覆盖 env） | 不写入本文件；网页与接口只显示掩码；无 Key 时提炼自动关闭，转写不受影响 |
| PC 服务连接密钥 | **1.4 起不再使用**；即使旧配置仍有 `WORKER_TOKEN`，当前代码也不读取 | 无需填写或恢复；旧版本文件可能仍有历史字段 |
| NAS 电脑地址设置 | `/data/jobs.sqlite3` 的 `settings` 表（1.4 起仅存地址与开关，不再存密钥） | 默认地址 `http://192.168.1.73:18788` 已内置，无需导入任何文件 |
| NAS 会话签名密钥 | `/data/.session-secret` | 自动生成并持久化，权限 0600；升级/备份时保留 |
| ECS 应用凭据 | `/opt/atow/app.env` | root 只读权限 0600；并不包含 SSH 密码 |
| ECS SSH 登录密码 | 未写入项目文档 | 不能把网页口令拿去当 SSH 密码 |

旧参数 `REMOTE_WORKER_URL` 仍兼容（作为默认地址覆盖）；`REMOTE_WORKER_TOKEN` 在 1.4 起不再使用。1.5 新增 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` / `LLM_ENABLED` 环境变量（仅作初始默认值，默认百炼专属端点 + kimi-k3），网页“AI 提炼设置”保存后随时覆盖；发布包 `nas.env` 中这些行为注释掉的模板。

NAS 内部的数据包括：

```text
/data/jobs.sqlite3       jobs / settings / job_events
/data/.session-secret   会话签名密钥
/data/<任务ID>.upload    待处理的原录音，终态清理
/data/<任务ID>.wav       本机转换文件，终态清理
```

备份 SQLite 时，停止应用后复制整个数据目录，或使用 SQLite 在线备份，注意 WAL；不要只复制一个正在写入的 `.sqlite3` 文件。

NAS 默认以 UID/GID 10001 运行，入口会修改**挂载目录自身**的所有者。必须使用专用数据文件夹，不能挂 NAS 共享根目录或其他业务目录。支持非零 `PUID`、`PGID`。

## 7. 任务、终止、日志与文件生命周期

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
- 已终止任务保留日志和记录，允许用户再删除。已完成/失败/终止记录按 7 天保留策略处理。
- 取消会清空部分文字，防止误把不完整输出当成完成结果。

清理策略：NAS 保留原录音直到远程结果成功保存，或本机结束/终止，再删除；PC 结束或失败就删除原文件和 WAV，NAS 确认后删除 PC 结果元数据。未确认的 PC 文字元数据最多留一小时，音频已提前清理。

容器日志与网页 `job_events` 含任务名、开始时间、实际设备/引擎、调度原因、完成耗时、终止和清理。应用日志使用显式 `+04:00`，NAS 日志界面的外层时间可能按 NAS 自身时区显示；网页按设备时区。旧记录不补造历史耗时、引擎或日志。

## 8. 已完成的开发里程碑

以下按版本顺序记录开发过程（1.4 及之前为 2026-10-25，1.5 为 2026-10-27），版本顺序优先于旧文档段落顺序：

| 阶段 | 完成内容 | 实际交付 / 验证 |
| --- | --- | --- |
| 初始 ECS 版 | SSH 检查、CPU 服务、手机网页、认证、后台队列、HTTPS IP 证书和续期 | ECS 实际部署；中文/英文、静音/损坏文件、常见格式、下载、清理验证 |
| 记录版 | 录音时长、实际处理耗时、开始/完成时间、记录点击详情，兼容旧数据 | ECS `records-v2` 实际部署，旧记录保留验证 |
| 需求纠正 | 移除额外添加的网页录音入口 | 用户只要上传；页面不调用麦克风 |
| NAS 1.1 | ARM64 镜像、内置模型、桥接端口、HTTP/Tailscale、独立持久化 | 用户已自行在 Z2 Pro 创建并运行；解决未填 ACCESS_CODE、端口占用问题 |
| 混合 1.2 | 真实 RTX 5080 FunASR 服务、LAN 分发、CPU 回退、两端清理、登录自启 | 模拟 ARM64 NAS 调用实际 GPU 通过；物理 NAS 运行了混合版界面但没有启用远程配置 |
| 可观测 1.3 | 网页导入/测试电脑连接、按任务读取配置、具体失败原因、详细任务日志、无 ANSI 颜色 | 配置缺失、错误密钥、端口拒绝、重启持久化、实际 GPU 转写验证 |
| 终止 1.3 | 排队/CPU/GPU 终止、清理后终态、重启恢复、取消/断线竞争处理 | 公开样例合成一小时录音，实际 GPU 终止及下一任务验证，手机按钮验证 |
| 免密钥 1.4 | 去掉 NAS↔电脑密钥校验；默认电脑地址内置；网页改为在线状态显示（15 秒自动刷新），仅保留地址修改；CPU 回退与终止逻辑不变 | 语法检查、无密钥真实 GPU 回路、14 项 QA（零配置直连/回退原因/重启保留/日志/排队与 CPU/GPU 终止/浏览器状态卡与手机布局）全部通过；1.4 镜像与 ZIP 已构建交付 |
| AI 提炼 1.5 | NAS 端 OpenAI 兼容 API 提炼（默认百炼专属端点 + kimi-k3）、`LLM_*` env + 网页设置双通道、详情页 AI 内容/原文双页签（默认 AI）、随时一键生成/重新生成（换模型或补配置后点一下即可）、摘要要求具体信息、非 200 错误透出服务商原因、不发送 temperature（kimi-k3 等推理模型拒绝该参数）、原始转写永久保留；识别链路降噪调优（FFmpeg highpass/lowpass、Silero 0.6、`speech_noise_thres` 0.75）；网页首屏 401/favicon 控制台报错修复 | 单测 10/10；隔离 ARM64 QA 容器 Phase A 3/3、Phase B 7/7、浏览器 10/10；真实端点验证（kimi-k3 全形状 200、摘要含日期/人名/数字/期限）；真实 RTX 5080 回归 7+4；1.5 镜像与 ZIP 已构建交付（2026-10-28）。电脑服务重启与真实录音 A/B 验收待用户参与 |

## 9. 测试、证据与测试边界

### 已通过

以下运行测试均为历史验证。2026-10-27 本次为 1.5 发布：在最终镜像 `shengjian:1.5.0-arm64` 上完成 AI 提炼 QA（单测、Phase A/B、浏览器）与真实 RTX 5080 回归，并完成发布打包核验（docker load、架构、ZIP 解压、包内无密钥扫描）；全程使用隔离 QA 容器与临时卷，未触碰生产容器、电脑 GPU 服务与物理 NAS。

- ECS：真实 HTTPS 证书、中文/英文、M4A/MP3/WebM/WAV、静音/错误音频、TXT、音频删除、手机布局。
- ARM64：真实 ARM64 镜像和 Python、归档导入、内置模型、HTTP 认证、会话和记录重启保留。
- 混合调度：模拟 NAS → LAN 地址 → 真实 RTX 5080；电脑未就绪、忙碌、错误和处理中断回退 CPU。
- 1.3：网页导入与诊断、错误密钥和端口原因、无远程环境变量时的配置保存/重启、无密钥泄露和 ANSI 字符。
- 终止：排队任务、运行中的 CPU/GPU、两端文件删除、终止后下一 GPU 任务、重复终止、取消/断线竞争、重启后完成清理。
- 数据迁移：旧记录文字与时间保留，不捏造未采集的历史值。
- 浏览器：390×844 手机尺寸，导入连接、设备/引擎、日志、终止、TXT 下载、刷新，无脚本错误和横向溢出。
- 1.4 免密钥（2026-10-25，Docker Desktop ARM64 模拟 + 真实 RTX 5080）：
  - 语法检查（py_compile）与网页 JS 语法检查通过；期间发现并修复一处网页 JS 括号错误（登录后界面不显示），修复后重新构建镜像并全部重测。
  - 真实 GPU 回路：无任何 Authorization 头 probe/upload/轮询/结果确认全链路通过（5.59 秒样例音频）。
  - `verify-observability.py` 7 项 PASS：零配置默认地址直连真实 RTX 5080、空地址/拒绝连接/关闭开关的明确回退原因、网页保存地址、重启后设置/会话/日志保留、容器日志无 ANSI 且元数据完整。
  - `verify-cancellation.py` 4 项 PASS：排队终止、CPU 终止 0.6 秒、真实 GPU 推理中终止 1.3 秒且两端清理、终止后下一 GPU 任务成功且重复终止幂等。
  - `browser-settings-check.cjs` 3 项 PASS：零配置状态卡显示电脑在线（默认地址）、任务元数据/日志/TXT 下载/手机布局、终止后状态与设置持久化、无浏览器错误。
  - 打包核验：tar manifest 架构 arm64、ZIP 完整性 OK、包内无 computer-connection.json、包内 worker 代码无密钥逻辑。
  - QA 容器 `atow-logs-qa` 与临时卷已清理；电脑 GPU 服务保持运行（免密钥新版）。
- 1.5 AI 提炼与调优（2026-10-27，Docker Desktop ARM64 模拟 + 真实 RTX 5080 回归）：
  - 单测 `tests/test_llm_refine.py` 9/9：普通/围栏/前缀 JSON 解析、垃圾响应与 HTTP 500 重试、401 不重试、超时、缺配置、非对象 JSON。
  - `verify-refine.py a`（容器不带 LLM 环境变量）3 项 PASS：1.4 旧 schema 库自动迁移且旧记录可读、env 未配置时取默认值（默认端点/kimi-k3/无 Key）、无 Key 不触发提炼。
  - `verify-refine.py b`（stub LLM 服务）7 项 PASS：env 全链路（Key 掩码、自动提炼、refined_text/summary 精确匹配、事件含“提炼”）、网页覆盖与解析失败路径、失败后重新提炼、提炼中并发请求 409、网页关闭开关不提炼、refined/summary/original 三种下载、容器外网连通真实模型端点。
  - `browser-refine-check.cjs` 9 项 PASS：AI 设置卡（开关/地址/模型/Key/测试连接）、UI 保存与连接测试、上传自动提炼、详情页默认 AI 页签且标注 AI 生成、原文页签切换、概要复制/下载、390px 无横向溢出、页签卡片布局正常、全程无控制台报错。
  - 回归：`verify-observability.py` 7 项 PASS、`verify-cancellation.py` 4 项 PASS（零配置直连真实 RTX 5080、回退原因、重启保留、排队/CPU/GPU 终止与双端清理）。
  - 期间发现并修复网页首屏未登录 401 探测与 favicon 404 控制台报错（提交 `d67ff66`），修复后重建镜像并从 Phase A 起全量重跑，以上证据均出自修复后镜像。
  - 打包核验：`docker load -i` 输出 `Loaded image: shengjian:1.5.0-arm64`、镜像架构 arm64、ZIP 解压 14/14 文件且解压后 tar 哈希与源一致、包内文本无任何 API Key 且无 `computer-connection.json`。
  - QA 容器 `atow-logs-qa` 与临时卷已清理；**电脑 GPU 服务未重启，仍运行 1.4 代码**。
  - 评审修复波（同日，提交 `c7a5282`）：AI 页签"下载 TXT"随提炼状态禁用（提炼 running/failed 时禁用，避免跳到 409 JSON 页；原文页签对已完成任务保持可用）、登出重置 `llmLoaded` 设置加载标志。修复后重建镜像、重打包并重跑浏览器回归：`browser-refine-check.cjs` 9 项 PASS；另按 API 把模型切到 `stub-garbage` 触发提炼失败后刷新详情页，断言 AI 页签下载按钮禁用、切回原文页签恢复可用（4 项断言全过）。发布物校验值更新为修复后产物（见第 5 节），包内镜像 grep 确认含两处修复；QA 容器与临时卷清理零残留，电脑 GPU 服务仍未重启。
  - 热修复波（2026-10-28，提交 `ef5a2c9`/`756f203`/`1be9d95`）：用户实机首次提炼报"AI 服务返回 HTTP 400"，用真实凭据定位根因为 kimi-k3 拒绝 `temperature` 参数（百炼返回 `Parameter 'temperature'=0.2 is not supported for kimi-k3 model`）。修复：请求不再发送 temperature；非 200 错误把服务商返回原因（截断 200 字符）带进错误信息；摘要提示词要求每点为具体信息（决定/数字/名字/日期/待办）并禁止泛泛描述；AI 页签支持随时一键生成/重新生成（未配置时转写的任务在配置后出现"生成 AI 内容"按钮，done/failed 显示"重新提炼"）。验证：单测扩到 10/10（stub 模拟 temperature 拒绝 + 错误详情断言）；真实端点全形状请求 200，强化后的提示词产出含日期/人名/预算数字/期限的具体摘要且口水词全清；热修复镜像上 Phase B 7/7、浏览器 10/10（新增"关闭 AI 转写→开启→按钮生成"场景）；QA 容器与临时卷清理零残留。
  - 1.5.1 版本化重打包（2026-10-28）：热修复未升版本号导致 1.5.0 新旧包无法通过 `/api/health` 区分（用户反馈"重新生成按钮没做"实为 NAS 仍运行热修复前镜像）。升版本 1.5.1（app.py health、compose、README、BUILD-INFO 同步）并重打包到 `dist/shengjian-1.5.1/`；验证容器实测 health 返回 `"version":"1.5.1"`，SHA256SUMS 13/13、架构 arm64。
  - 1.5.2 流式修复（2026-10-28，提交 `ebe8b9f`/`134d184`）：用户实机长录音提炼报"无法连接 AI 服务：The read operation timed out"。根因：非流式请求下服务器需全部生成完才发首字节，kimi-k3（推理模型）对长转写的思考+全文重写超过 120 秒读取超时。修复：LLM 请求改为 SSE 流式（`stream: true`），超时作用于相邻数据块之间，模型持续输出即不中断；流内 error 对象透出消息；单测扩到 11/11（stub 同步改 SSE 协议，新增流内错误用例）；真实端点流式验证 9304 字转写 11 秒返回、摘要 10 条全为具体数字；QA stub `stub-llm.py` 同步改 SSE；镜像上 Phase B 7/7、浏览器 10/10。
  - 1.5.3 版本号显示（2026-10-28，提交 `b53d5c4`）：应用户要求，网页右上角状态区下显示当前版本号（读取 `/api/health` 的 version 字段，以后升版本自动跟随，无需改网页）。验证容器实测 health 返回 `"version":"1.5.3"`，浏览器实测页面显示 `v1.5.3`、无控制台报错（截图 `test-results/version-display.png`）；重打包 `dist/shengjian-1.5.3/`，SHA256SUMS 13/13、架构 arm64。
  - 1.5.5 结构化摘要（2026-10-28，提交 `54c76b3`）：应用户要求，摘要按大类分类组织并单列【遗留任务】（负责人+期限）。采用单次调用直接产出结构化摘要（分类时模型可见完整转写原文，信息不丢失；用户原建议的二次加工方案未采用，如质量不满意可随时加链）。真实端点实测：kimi-k3 单次调用 12 秒返回，自动产出 5 个大类（预算/产品优化/服务器迁移/采购/合同续签）+ 4 条带负责人和期限的遗留任务（证据 `test-results/structured-summary-check.txt`）；单测 11/11 不受影响；重打包 `dist/shengjian-1.5.5/`，SHA256SUMS 13/13，验证容器 health 返回 `"version":"1.5.5"`。
  - 1.5.4 提炼日志时间线（2026-10-28，提交 `3c7bb4d`）：应用户要求，每次 AI 提炼把开始事件（模型名、转写字数）写入容器日志，`docker logs` 可见完整时间线（转写完成 → AI 提炼开始 → 完成/失败），长录音提炼期间不再日志静默。1.5.4 镜像上 Phase B 7/7，容器日志实测含"AI 提炼开始：模型 stub-ok，转写 14 字"与对应完成/失败行；重打包 `dist/shengjian-1.5.4/`，SHA256SUMS 13/13、架构 arm64。

一次取消测试观察到 CPU 清理约 0.7 秒、真实 GPU 清理约 1.5 秒，仅是该测试结果，不是所有设备的响应保证。

### 用户提供的性能基准

`c9.xlarge.4`，4 核 16 GB：1 小时 52 分钟（6720 秒）音频，耗时 2 分 54 秒（174 秒）。约 38.6 倍实时速度，RTF 约 0.026。这是用户实测，不能用于推算 Z2 Pro、不同模型或 GPU 的同音频耗时。

### 测试入口

| 文件 | 目标 / 说明 |
| --- | --- |
| `deploy/verify.py` | 原 ECS 环境，读取服务器应用配置；会创建并清理测试任务 |
| `deploy/browser-check.cjs`、`records-check.cjs` | 历史 ECS 浏览器与记录测试 |
| `deploy/migration-check.py` | 在镜像内运行，隔离临时 SQLite，不启动真实识别 worker |
| `deploy/nas/verify-arm64.py` | 早期 1.1 ARM64 测试，有旧镜像/容器名，不应直接当当前版本入口 |
| `deploy/nas/verify-hybrid.py`、`fault-worker.py` | 1.2 混合调度和故障模拟，需要隔离 QA 容器 |
| `deploy/nas/verify-observability.py` | 当前 1.4 零配置直连、网页地址设置、具体失败原因、日志、实际 GPU 与重启 |
| `deploy/nas/verify-cancellation.py` | 排队/本机/实际 GPU 终止与音频清理，使用公开合成的一小时 WAV |
| `deploy/nas/verify-cancel-race.py` | 取消与断线竞争、重启恢复，隔离临时数据库 |
| `deploy/nas/browser-settings-check.cjs` | 当前 1.4 无导入/无密钥状态卡、任务日志、终止、下载与手机 QA；会重置隔离 QA 的设置 |
| `deploy/nas/stub-llm.py` | QA 用容器内 stub OpenAI 兼容服务（按 model 名分流正常/垃圾响应/500/延迟），不是产品组件 |
| `deploy/nas/verify-refine.py` | 1.5 AI 提炼两阶段容器验证（`a`：无 env 默认与旧库迁移；`b`：stub 全链路），需要隔离 QA 容器 |
| `deploy/nas/browser-refine-check.cjs` | 1.5 AI 设置卡、双页签、概要复制/下载与手机 QA；会重置隔离 QA 的设置 |
| `tests/test_llm_refine.py` | 提炼客户端单测（9 项：解析变体、重试、401 不重试、超时、缺配置、非对象 JSON） |

**不要把测试脚本中的 QA 容器名改成用户的生产容器直接执行。** 测试会上传/删除任务，部分还会重启容器、清空 QA 连接设置。应先阅读脚本中的固定端口、名称、路径和测试前置条件。

本次测试容器 `atow-logs-qa`、`atow-hybrid-qa`、`atow-fallback-qa` 及对应临时卷已清理；电脑 GPU 服务有意保持运行。模型与发布包保留。

测试截图在 `test-results/`，主要是 `settings-and-task-logs.png`、`cancelled-task.png`、`refine-browser.png`（1.5 提炼浏览器 QA 全页截图），不含真实用户转写内容或明文密钥。

## 10. 运维与重建速查

### 检查 NAS 版本

```powershell
Invoke-RestMethod 'http://192.168.1.66:18088/api/health'
```

1.5.5 应返回 `version: 1.5.5`（物理 NAS 升级前仍返回旧版本；网页右上角状态区下也直接显示 v1.5.5）。健康接口显示 ready 不等于电脑加速已经连通；后者看网页“电脑加速”状态卡。

### 检查电脑 GPU 服务

电脑服务不需要密钥；**截至 2026-10-27 仍运行 2026-10-25 重启的 1.4 代码，1.5 调优需再次重启后生效**。可用以下请求检查当前状态：

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
  --tag shengjian:1.5.5-arm64 --file deploy/nas/Dockerfile .

docker buildx build --platform linux/arm64 --provenance=false `
  --tag shengjian:1.5.5-arm64 --file deploy/nas/Dockerfile `
  --output type=docker,dest=dist/shengjian-1.5.5/shengjian-z2pro-arm64.tar .
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

## 11. 已遇到的问题和应避免重复的误判

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

## 12. 已知限制与后续候选工作

尚未实现或未确认：

- 物理 Z2 Pro 升级 1.5，以及 NAS 实机 → PC 的免密钥闭环联调与 AI 提炼实机验证；无需连接配置导入。
- 电脑 GPU 服务重启到 1.5 代码（调优参数重启后才生效），以及真实噪声录音的 A/B 对照验收；调优参数（FFmpeg 滤镜、Silero 0.6、`speech_noise_thres` 0.75）尚未用真实录音验证。若实测识别质量变差：单独回滚调优参数（`speech_noise_thres` 回 0.6、Silero 回 0.5、去掉 `-af` 滤镜）重建重测，不影响 AI 提炼功能。
- 同一份长录音在 Z2 Pro、ECS、RTX 5080 的严格对照基准。
- 暂停、断点续跑、任务跨重启续算；目前普通任务重启会重新处理。
- 自动 LAN 设备发现；当前靠固定地址/网页修改，建议 DHCP 地址保留。不要声称地址变化已自动发现。
- GPU 的精确音频百分比进度；当前主要是上传/转换/识别阶段进度，停在某个阶段不自动等于挂死。
- NAS SSH 管理权限与原数据目录实际路径未记录，不能假设已具备自动更新 NAS 的能力。
- 长期需要处理 ECS 的旧操作系统/运行时维护；这不属于当前 NAS 升级已完成项。
- AI 提炼的 LLM 调用在转写队列线程内同步执行，长录音提炼期间下一条排队任务最多等待约 240 秒（单用户场景已接受；如后续排队频繁可改为异步执行）。
- `llm_refine` 对含无效端口的 API 地址报错文案会误标为"AI 返回格式无法解析"（仍会正确失败，仅文案不准）。
- 网页"内容概要"的复制按钮在剪贴板 API 不可用的环境没有 execCommand 兜底（顶部复制按钮有）。
- 发布包内 README 的"验证范围"段仍为 1.4 时代清单；1.5 验证证据以包内 BUILD-INFO.json 与本文件第 9 节为准，后续可补 1.5 摘要。

Windows 服务不是系统级服务，未登录、休眠或关机时不会可用，NAS 按设计回退。录音完成后不保留服务器原文件，因此再次转写/回放原音频需要用户重新上传。

## 13. 后续工作如何更新这份文档

每次完成开发或排障后，更新这几个位置即可：

1. 第 1 节的最新版本、实际部署状态和检查时间。
2. “下一步从这里继续”的未完成事项。
3. 新增/修复的功能和相关文件地图。
4. 实际跑过的验证、测试环境、结果和限制。
5. 新发布文件、镜像标签与校验值。

区分“代码完成”“镜像完成”“模拟验证”“物理 NAS 实机验证”和“实际部署生效”。不要只追加历史段落却不更新当前状态。主文档不得写入密码、连接 token、会话密钥或用户真实转写内容。

可直接使用的接续提示：

> 读取 `F:\Codex Project\atow\PROJECT_STATUS.md`，先核实当前运行版本和未完成事项，在保留原数据及用户既定需求的前提下继续工作；完成后更新这份主文档。
