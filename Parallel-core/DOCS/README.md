# ParallelVerse 项目文档

本文档目录对应后端：

```text
Pro/Parallel-core
```

## 文档导航

| 文档 | 内容 |
|---|---|
| [01-项目概览与架构.md](01-项目概览与架构.md) | 功能范围、模块职责、核心数据流 |
| [02-启动与部署.md](02-启动与部署.md) | 本机启动、局域网访问、HTTPS 注意事项 |
| [03-配置说明.md](03-配置说明.md) | `.env` 字段、Key 分工、Prompt 配置 |
| [04-接口与消息协议.md](04-接口与消息协议.md) | HTTP 与 WebSocket 接口、主要事件 |
| [05-开发指南.md](05-开发指南.md) | 目录结构、修改入口、测试与开发约束 |
| [06-日志与故障排查.md](06-日志与故障排查.md) | 摄像头、Talker、Interaction、Voice 排障 |
| [07-演示Mock说明.md](07-演示Mock说明.md) | 当前两条演示 Mock 的触发与维护方式 |

## 快速启动

```bash
cd Pro
./start.sh
```

默认监听 `0.0.0.0:8010`。本机访问：

```text
http://127.0.0.1:8010
```

测试：

```bash
cd Pro/Parallel-core
.venv/bin/python -m pip install -r requirements-dev.txt
PYTHONPATH=. .venv/bin/pytest -q
```

## 当前状态

- Video Edit：可用，点击“开启穿越”后调用。
- Talker：可用，负责实时 ASR、普通对话和语音回复。
- Interaction：可用，负责分析原始摄像头画面。
- Voice：可用，使用 `tts_text` 朗读 Interaction 或 Mock 文本。
- 测试基线：`38 passed`。
