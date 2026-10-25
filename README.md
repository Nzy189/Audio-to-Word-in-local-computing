# 声笺

上传已有录音，后台转写；NAS 优先调用局域网 Windows RTX 5080，不可用时使用 NAS CPU。

## 开发进展与接续

**先读 [PROJECT_STATUS.md](PROJECT_STATUS.md)。**

它是本项目唯一的开发状态主文档，集中记录：需求、架构、设备和地址、代码地图、版本与实际部署、验证结果、问题处理、凭据位置、运维命令、已知限制和下一步。

项目入口 [AGENTS.md](AGENTS.md) 已要求后续工作先读取主文档，并在工作完成后更新。

## 最新安装包

- [1.4 完整安装包](dist/shengjian-1.4.zip)
- 镜像：`shengjian:1.4.0-arm64`
- [NAS 用户升级说明](deploy/nas/README.md)
- [Windows GPU 服务说明](worker/README.md)

构建完成不等于物理 NAS 已升级。真实部署状态和最新检查时间见主文档，继续使用原数据挂载与 `18088 → 8787`。

运行口令保存在相应运行配置中，不写入开发状态文档。
