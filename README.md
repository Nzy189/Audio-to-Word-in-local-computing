# 声笺（Shengjian）

[English](README_EN.md) | **简体中文**

> 上传已有录音，自动转成文字。NAS 网页接收文件，任务自动优先使用局域网内的
> Windows RTX 5080（FunASR CUDA）转写；电脑关机或不可用时自动回退 NAS CPU
> （sherpa-onnx）。内网单人使用，NAS 与电脑之间无需任何密钥。

开发进度、部署核查与接续步骤以 [PROJECT_STATUS.md](PROJECT_STATUS.md) 为准；本文件是项目入口。

---

## 工作方式

```text
手机上传已有录音
    → NAS 网页接收并持久化任务
    → 自动检测电脑转写服务
         ├─ 电脑开机：局域网 → Windows FunASR / RTX 5080 → 结果回到 NAS
         └─ 关机/忙碌/出错：NAS 本地 sherpa-onnx CPU，日志给出具体原因
    → 保存文字、设备、耗时与任务日志
    → 清理两端录音与临时文件
```

## 功能

- 上传已有音频文件（MP3 / M4A / WAV / WebM 等），单个最大 300 MB、最长 3 小时；不调用麦克风，不做实时转写。
- 电脑开机即默认用 GPU 转写，零配置：默认电脑地址已内置，网页“电脑加速”卡片实时显示在线状态。
- 自动回退：电脑关机、休眠、忙碌、显存不足或出错时改用 NAS CPU，任务日志说明为什么没有使用电脑。
- 任务记录：录音时长、处理耗时、提交/开始/完成时间、实际设备与引擎，点击查看全文，支持复制与 TXT 下载。
- 终止任务：排队、NAS CPU、电脑 GPU 任务均可终止，两端临时音频清理后才显示终态。
- 自动识别中文、英文、粤语、日语和韩语；文字记录保留 7 天。

## 安装与运行

- **极空间 Z2 Pro（ARM64 NAS）**：见 [deploy/nas/README.md](deploy/nas/README.md)。导入镜像、挂载原 `/data`、保留网页口令即可，无需任何电脑配置文件。
- **Windows GPU 服务**：见 [worker/README.md](worker/README.md)。复用现有 FunASR 环境，登录 Windows 后自启。

## 项目结构

| 目录 / 文件 | 职责 |
| --- | --- |
| `service/` | NAS 端 FastAPI 应用：上传、调度、本地 CPU 转写、网页、任务日志 |
| `worker/` | Windows 端 FunASR CUDA 服务：单任务 GPU 转写、取消、清理 |
| `deploy/nas/` | ARM64 镜像、Compose、安装说明与 QA 测试脚本 |
| `deploy/`（其余） | 原 ECS 部署与运维文件 |
| `PROJECT_STATUS.md` | 开发状态主文档：进度、验证、地址、凭据位置、下一步 |

当前版本 1.4（免密钥电脑加速）。构建完成的安装包位于本地 `dist/`，不入库；真实部署状态以 PROJECT_STATUS.md 为准。
