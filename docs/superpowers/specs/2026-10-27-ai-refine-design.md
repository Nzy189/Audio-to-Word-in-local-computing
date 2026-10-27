# 声笺 1.5 设计：AI 提炼 + 识别链路轻量调优

日期：2026-10-27。状态：设计定稿（用户已确认方向），待实施计划。

## 1. 背景与目标

用户反馈转写结果"噪声大"：大量口水词（额、嗯、哼）被逐字转出，同音错别字多，夹杂无意义的识别输出。经确认：

- 录音以中文为主，少量全英文，`language` 保持 `auto` 不动。
- 痛点主体（口水词、错别字）是真实人声，VAD 调严砍不掉，**AI 提炼是对症的方案**。
- 转写文字**可以**发云端 API；期望输出**原始转写 + AI 优化原文 + 精简概要**三者并存。
- 用户选定方案：AI 提炼为主 + 识别链路轻量调优（FFmpeg 滤镜 + VAD 阈值）。

## 2. 数据流

```
转写 done（原始文字已保存，现有状态机不变）
→ 读 settings 表 llm_refine 配置；未启用或未配置 → 无提炼，行为同 1.4
→ 已启用 → 后台执行提炼（不阻塞转写结果展示）
→ POST {base_url}/chat/completions（OpenAI 兼容格式）
→ 一次调用返回 {"corrected": 优化原文, "summary": 概要}
→ 存 jobs 表新列；详情页显示三块内容
→ 失败/超时：任务仍是 done，refine_status=failed + 原因，可点"重新提炼"
```

提炼在 **NAS 端**执行：任务与数据都在 NAS，电脑关机走 CPU 路径时同样可用。NAS 容器需有外网出口——实现时第一个验证点。

## 3. 配置与数据模型

### settings 表新增键 `llm_refine`

JSON 结构：`{"enabled": bool, "base_url": str, "model": str, "api_key": str}`

- 默认值：`base_url = https://dashscope.aliyuncs.com/compatible-mode/v1`（阿里百炼 OpenAI 兼容端点），`model = qwen-plus`。换 DeepSeek 等其他平台只需改地址和模型名。
- `api_key` 只存 NAS SQLite（`/data/jobs.sqlite3`），不进代码、日志、PROJECT_STATUS 和发布包。网页有口令保护，单人内网使用，可接受。
- 配置读写走与 `remote_worker` 相同的 settings 模式。

### jobs 表新增列（启动时自动迁移，兼容旧库与旧记录）

| 列 | 含义 |
| --- | --- |
| `refine_status` | `none` / `running` / `done` / `failed` |
| `refined_text` | AI 优化后的原文 |
| `summary` | AI 概要（bullet points） |
| `refine_error` | 失败原因（不含 key） |
| `refine_at` | 提炼完成时间 |

7 天保留策略覆盖新字段。取消/终止任务不做提炼。

## 4. LLM 调用

- 标准库 `http.client` + `json`，与 `service/remote_worker.py` 一致，**不加新依赖**（requirements.txt 不变）。
- 请求：OpenAI 兼容 `POST {base_url}/chat/completions`，`Authorization: Bearer {api_key}`，`messages` = [system 提示词, user 原始转写]，`temperature` 低值（0.2）。
- 超时 120 秒；网络/超时/5xx 重试 1 次；JSON 解析失败时追加"只输出 JSON"的更强指令重试 1 次；仍失败则 `refine_status=failed`。
- 解析容错：剥离 ```json 代码围栏后再 `json.loads`。
- 长文本：3 小时录音约 5~10 万字，qwen-plus / deepseek-chat 的 128K 上下文可容纳，不做分段合并。
- 提炼在转写完成后于同一处理线程顺序执行（NAS 本就逐条处理任务），不引入并发。

### 提示词（system，实现以此为准）

```
你是语音转写文稿的整理助手。输入是一段语音识别的原始转写文字，可能包含同音错别字、
语气词和无意义重复。

请输出严格的 JSON 对象，包含两个字段：

"corrected"：优化后的完整原文。
- 修正同音字和明显的识别错误
- 删除"额""嗯""哼""啊"等无意义语气词
- 删除无意义的重复词句
- 不改写句式，不增删信息，不改变原意，不改变语言
- 保留原文的段落结构

"summary"：内容概要。
- 用精简的要点列表（bullet points）呈现，每点一行
- 只保留核心信息：做了什么、决定了什么、关键数据
- 不写引言和套话，不复述原文

只输出 JSON，格式：{"corrected": "...", "summary": "..."}，不要输出任何其他内容。
```

## 5. API 接口（会话校验与现有一致）

| 接口 | 作用 |
| --- | --- |
| `GET /api/llm-config` | 返回配置（api_key 脱敏显示，如 `sk-***`） |
| `POST /api/llm-config` | 保存配置 |
| `POST /api/llm-config/test` | 发一条最小请求验证地址/key/模型可用 |
| `POST /api/jobs/{job_id}/refine` | 对已完成任务手动重新提炼 |
| `GET /api/jobs/{job_id}` | 返回值增加新字段 |

## 6. 网页 UI（service/index.html）

- 设置页新增"AI 提炼"卡片，与"电脑加速"卡片同款交互：开关、API 地址、模型名、API Key 输入、"测试连接"按钮、保存。
- 任务详情页改为两个页签切换，**默认停在"AI 内容"页签**：
  - **AI 内容**（默认页签）：上方"AI 优化原文"、下方"内容概要"两块，明确标注 AI 生成；各带复制与 TXT 下载；`running` 显示进行中；`failed` 显示原因 + "重新提炼"按钮。
  - **原文**：原始转写，保留现有复制与 TXT 下载。
- 未配置/未启用 LLM 时，详情页保持现有单块原文展示，不显示页签；提炼进行中或失败时页签照常显示对应状态。
- 手机布局照例 390×844 检查，无横向溢出。

## 7. 识别链路轻量调优（两端同步）

| 位置 | 改动 |
| --- | --- |
| `worker/server.py` FFmpeg 命令 | 加 `-af "highpass=f=80,lowpass=f=7500"` |
| `service/app.py` 本机 FFmpeg 转换 | 同上 |
| GPU 侧 FSMN VAD（`vad_kwargs`） | 噪声判定阈值调严一档（参数名与取值实现时对照 FunASR 文档/源码验证，从默认约 0.5 提至约 0.65） |
| NAS 侧 Silero VAD | `threshold` 0.5 → 0.6（[service/app.py:246](../../../service/app.py)） |
| `language` | 保持 `auto` |

验证方式：同一段真实录音改前/改后 A/B 对照；滤镜与阈值**分开**验证，哪个变差回滚哪个。此改动对口水词无效（预期如此），目标是减少纯环境噪声段。

## 8. 验证计划

1. NAS 容器到百炼端点的连通性（实现第一步）。
2. 迁移：旧库加列后旧记录可读，`refine_status=none`。
3. 失败路径：错误 key、超时、返回非 JSON——任务仍 done，原因清晰。
4. 真实回路：隔离 QA 容器 + 真实 key + 一段真实录音，转写 → 提炼 → 详情页三块显示、复制、下载。
5. 识别调优 A/B 对照（真实录音）。
6. 手机布局与浏览器无脚本错误。
7. 全程隔离 QA 容器/临时卷，不碰生产 NAS；测试后清理。

## 9. 交付物

- 版本 1.5.0；镜像 `shengjian:1.5.0-arm64` + ZIP 发布包，同步 compose、BUILD-INFO、README、PROJECT_STATUS。
- 电脑端 `worker/server.py` 有改动，交付后需择空闲时重启电脑 GPU 服务（届时提醒用户，先查 busy）。
- ECS 不动。

## 10. 风险与边界

- LLM 可能偶尔改写原意 → 原始转写永远保留并置于首位，AI 内容明确标注。
- NAS 容器外网出口未验证 → 实现第一步验证，不通则给用户明确的排查指引。
- 百炼/DeepSeek 需用户自行注册充值获取 key → 用户操作，key 不经手开发过程。
- VAD 参数名需对照 FunASR 实际源码确认，不凭记忆写参数。
