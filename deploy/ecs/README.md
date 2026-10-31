# ECS 1.6.0 部署

开发状态和真实部署证据以 [PROJECT_STATUS.md](../../PROJECT_STATUS.md) 为准。本目录记录 ECS 升级要求及隔离 QA 入口。

## 目标与发布物

- 当前目标：`80.238.236.1`，CentOS 7 / x86_64，现有 Docker 26.1.4；升级前通过 SSH 重新核实。
- 镜像：`atow-transcriber:1.6.0-ecs`（`linux/amd64`）；本轮使用 `dist/shengjian-1.6.0-ecs/source.tgz` 在 ECS 复用原依赖就地构建。没有导出新的本地镜像 tar；NAS 的 ARM64 归档不能用于 ECS。
- ECS 复用 `/opt/atow/data:/data`、`/opt/atow/models:/models:ro` 和 `/opt/atow/app.env`；不打包网页口令、API Key、模型或业务数据。
- 应用监听 `127.0.0.1:8787`，继续由原 Nginx 提供 HTTPS。CPU 识别改用未量化的 SenseVoice FP32，设备标记为 `ECS CPU`；默认电脑地址留空，避免把家中 LAN 地址当作云端可达地址。
- 模型目录为 `/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/`，加载 `model.onnx`，不静默回退 INT8。原 INT8 模型目录保留供旧镜像回滚；旧任务保留原来的引擎字段，新任务显示 FP32。
- AI 提炼在网页“AI 提炼设置”中配置及测试，支持 OpenAI 兼容 API。无 API Key 时可正常转写；已有 ECS 环境变量和网页设置应保留。

## 本地构建与验证

在仓库根目录执行：

```powershell
python -X utf8 deploy/fetch-fp32.py
docker buildx build --platform linux/amd64 --load --provenance=false --tag atow-transcriber:1.6.0-ecs --file service/Dockerfile service
python -X utf8 tests/test_llm_refine.py
python -X utf8 deploy/ecs/run-qa.py
```

QA 为可选操作，需要现有 `build-assets/models/`（包含 FP32）和公开样例 `test-results/zh.wav`。脚本创建随机命名的容器，使用 tmpfs 作为数据目录；只挂载模型和公开样例，不挂载生产数据、不发布端口。AI 调用只访问容器内 stub。退出时移除 QA 容器和 tmpfs 数据。`verify-smoke.py` 必须在带 `ATOW_ECS_QA=1` 的隔离容器内运行，不得复制到生产容器执行。用户已要求跳过本轮功能测试，因此升级时仅做模型校验、启动及健康确认。

在已有 1.5.9 的 ECS 上，也可使用 `deploy/ecs/Dockerfile.upgrade`（构建上下文为源码根目录），显式传入 `--build-arg BASE_IMAGE=atow-transcriber:1.5.9-ecs`，沿用原依赖及运行参数。已有 FP32 模型无需重新下载；下载脚本只写入新的模型目录，校验大小与 SHA-256 后启用，不读取或更改凭据及业务数据。

1.6.0 需要在原库新增七列并回填旧提炼记录。`check-preservation.py` 可在迁移前后比较原记录字段、AI 设置与会话文件的摘要；以 UID 10001 运行，SQLite 连接使用只读模式，同时允许目录正常访问 WAL/共享内存元数据。参考文件只放在服务器受限备份目录，不把原文、Key 或会话密钥打印到日志。

导出用于上传的归档：

```powershell
docker buildx build --platform linux/amd64 --provenance=false --tag atow-transcriber:1.6.0-ecs --file service/Dockerfile --output type=docker,dest=dist/shengjian-1.6.0-ecs/atow-ecs-amd64.tar service
```

## 升级顺序

1. SSH 核查真实容器镜像、挂载、资源限制、健康状态及当前任务；等待转写和 AI 提炼结束。不要输出完整环境变量、数据库内容或用户转写文字。
2. 将新镜像上传到 `/opt/atow/` 下的独立发布目录，校验 SHA-256，使用现有 Docker 导入。先在服务器隔离容器中验证启动与 CPU 引擎，不占用生产端口。
3. 在切换前暂停新的上传，停止应用后备份整个原数据目录（包括 SQLite WAL、会话文件），另保留原启动脚本、原镜像及容器配置。备份仅留在服务器并限制权限。
4. 保留原容器以便回滚；新容器继续使用核实后的同一个数据目录、模型目录和 `app.env`。新版启动模板为 [start-app.sh](../start-app.sh)，默认镜像已更新；使用前应对照实际容器配置。
5. 验证本地及公网 `/api/health` 均返回 `ready: true`、`failed: false`、`version: 1.6.0`；核查旧记录摘要、设置、会话及 corrected_status 回填，公网页面摘要匹配交付文件。已有任务的硬件与 token 用量不补造。
6. 如用户要求功能验证，再用公开样例确认实际 `backend=local_cpu`、设备 `ECS CPU`、引擎 `SenseVoice FP32 / sherpa-onnx CPU`、清理和下载；不要自动重提炼已有用户记录。本轮不创建这些测试任务。
7. 若新版本启动或验证失败，停止新容器并恢复原启动配置。新版本尚未接收业务写入时可恢复切换前备份；已有新写入时先保全数据，不直接覆盖数据库。
8. 记录部署时间、镜像身份、实际检查及限制到主状态文档。保留回滚备份，不修改 NAS、Windows GPU 服务或其他业务容器。

本地构建及 QA 不能证明 ECS 已升级。SSH 尚未成功、健康接口没有返回新版版本号时，应明确记录为待部署。
