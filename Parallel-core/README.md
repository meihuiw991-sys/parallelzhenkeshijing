# ParallelVerse FrontAndModel

ParallelVerse 是一个基于摄像头的实时视频编辑与语音视觉交互应用。浏览器负责采集摄像头和麦克风，FastAPI 后端统一连接 JoyAI Video Edit、Talker、VL Interaction 和 Voice。

当前后端目录：

```text
Pro/Parallel-core
```

详细说明见 [`DOCS/README.md`](DOCS/README.md)。

## 当前功能

- 默认展示原始摄像头画面。
- 点击左下角“开启穿越”后，将摄像头帧发送给 JoyAI Video Edit 并展示渲染结果。
- Video Edit Prompt 从 `prompts/video-edit.txt` 读取，方便随时调整。
- Talker 持续接收麦克风 PCM16 音频，提供 Server VAD、ASR、普通对话和语音回复。
- 服务端根据 ASR 完整文本确定性判断是否需要视觉理解。
- VL Interaction 始终分析原始 `cameraVideo` 画面，不分析 Video Edit 的生成结果。
- Interaction 结果显示在右下角视觉解析卡片和中央字幕。
- JoyAI Voice 使用 `tts_text` 将 Interaction 结果转换为 PCM16/24kHz 音频并在浏览器播放。
- Interaction 第一次返回 `</silence>` 时会使用明确视觉指令自动重试一次。
- 前端会清理模型文本中的 Markdown `**` 标记。
- 历史弹窗保存并展示当前浏览器最近 50 轮真实问答，支持清空记录。
- 预留其他按钮和后续交互功能的扩展位置。

## 模型分工

| 模型 | 用途 | API Key |
|---|---|---|
| JoyAI Video Edit | 摄像头画面实时生成式渲染 | `MODEL_API_KEY` |
| JoyAI Talker | 实时 ASR、普通对话、普通回复语音 | `MODEL_API_KEY_2` |
| JoyAI VL Interaction | 原始摄像头画面理解 | `MODEL_API_KEY_2` |
| JoyAI Voice | Interaction 与 Mock 文本 TTS | `MODEL_API_KEY_2` |

Talker、Interaction 和 Voice 未配置 `MODEL_API_KEY_2` 时会回退使用 `MODEL_API_KEY`。

## 快速启动

首次启动会在项目目录自动创建本地虚拟环境：

```text
.venv
```

脚本要求 Python 3.11+，并优先选择 `python3.13`、`python3.12`、`python3.11`。检测到旧版 Python 创建的 `.venv` 时会自动重建。

推荐从上传目录根路径启动：

```bash
cd Pro
./start.sh
```

也可以直接启动后端：

```bash
cd Pro/Parallel-core
./start.sh
```

默认监听：

```text
0.0.0.0:8010
```

本机浏览器访问：

```text
http://127.0.0.1:8010
```

指定其他端口：

```bash
PORT=8080 ./start.sh
```

手动指定 Python：

```bash
PYTHON_BIN=python3.11 ./start.sh
```

首次启动需要访问 Python 包源，并根据 `requirements.txt` 安装依赖。项目运行不依赖 `Pro` 目录之外的文件。

首次启动前，从模板创建 `.env`：

```bash
cd Pro/Parallel-core
cp .env.example .env
```

填写实际 API Key 后再启动。`.env` 和 `.venv` 不应提交到仓库。

## 局域网访问

`start.sh` 已绑定 `0.0.0.0`，同一局域网设备可以通过本机局域网 IP 访问，例如：

```text
http://192.168.1.100:8010
```

查看 Mac Wi-Fi IP：

```bash
ipconfig getifaddr en0
```

注意：普通 HTTP 局域网地址通常不属于浏览器安全上下文，其他设备可能无法使用摄像头和麦克风。完整使用语音和视频采集能力时建议配置 HTTPS。

## 配置

项目从根目录 `.env` 读取配置，进程环境变量优先级更高。

核心配置示例：

```env
MODEL_WS_URL=...
MODEL_HEALTH_URL=...
MODEL_API_KEY=...
MODEL_API_KEY_2=...

MODEL_WIDTH=1248
MODEL_HEIGHT=720
MODEL_FPS=24
MODEL_INPUT_CODEC=mjpeg
MODEL_OUTPUT_CODEC=mjpeg
MODEL_OUTPUT_QUALITY=85
MODEL_GATE_ENABLED=false
MODEL_USE_PE=false

TALKER_WS_URL=ws://hubrouter.jd.com/v1/realtime?model=JoyAI-Talker
INTERACTION_URL=https://hubrouter.jd.com/v1/chat/completions
INTERACTION_MODEL=JoyAI-VL-Interaction
INTERACTION_TIMEOUT_SECONDS=20

VOICE_WS_URL=ws://hubrouter.jd.com/v1/realtime?model=JoyAI-Voice
VOICE_NAME=default
VOICE_OUTPUT_SAMPLE_RATE=24000
VOICE_TIMEOUT_SECONDS=30
```

不要将真实 `.env` 或 API Key 提交到公开仓库。

完整字段说明见 [`DOCS/03-配置说明.md`](DOCS/03-配置说明.md)。

## Prompt

| 文件 | 用途 |
|---|---|
| `prompts/video-edit.txt` | Video Edit 渲染指令，每次开启穿越时重新读取 |
| `prompts/talker.txt` | Talker 角色、回复和工具策略，新会话建立时加载 |

## 演示 Mock

当前保留两条精确匹配的演示 Mock，定义在 `app/demo_mocks.py`。

### Interaction Mock

问：

```text
请介绍眼前的景点
```

固定结果会显示在右下角视觉卡片，并通过 JoyAI Voice 朗读，不调用真实 Interaction API。

### Talker Mock

问：

```text
项羽有什么典故
```

系统会取消 Talker 自动回复，显示固定文案并通过 JoyAI Voice 朗读。

除以上两个精确问句外，其他输入继续调用真实模型。详细规则见 [`DOCS/07-演示Mock说明.md`](DOCS/07-演示Mock说明.md)。

## 历史对话

历史记录完全由前端实现，存储 Key：

```text
parallelverse.conversationHistory.v1
```

每轮在收到用户完整 ASR 文本后开始记录，在助手文字回复完成时写入 `localStorage`。记录包含用户文本、助手文本、完成时间和回答来源，最多保留最近 50 轮。

历史记录只保存在当前浏览器，不会写入后端，也不会保存音频、视频或图片。

## 主要接口

| 接口 | 说明 |
|---|---|
| `GET /` | 返回前端页面 |
| `GET /api/config/video-edit` | 读取当前 Video Edit Prompt |
| `GET /api/capabilities` | 返回前端能力开关 |
| `GET /api/health` | 返回本地服务和模型健康状态 |
| `WS /ws/render/{session_id}` | Video Edit 帧传输通道 |
| `WS /ws/assistant/{session_id}` | 麦克风、Talker、视觉快照、Interaction 和 Voice 通道 |

详细消息格式见 [`DOCS/04-接口与消息协议.md`](DOCS/04-接口与消息协议.md)。

## 目录结构

```text
Pro/
├── app/
│   ├── main.py
│   ├── assistant_session.py
│   ├── model_client.py
│   ├── talker_client.py
│   ├── interaction_client.py
│   ├── voice_client.py
│   ├── visual_router.py
│   ├── demo_mocks.py
│   └── static/
│       ├── index.html
│       ├── camera-render.js
│       ├── assistant.js
│       └── audio-capture-worklet.js
├── prompts/
├── tests/
├── DOCS/
├── start.sh
└── test_voice.py
```

## 测试

运行全量测试：

```bash
cd Pro/Parallel-core
.venv/bin/python -m pip install -r requirements-dev.txt
PYTHONPATH=. .venv/bin/pytest -q
```

当前测试基线：

```text
38 passed
```

JavaScript 语法检查：

```bash
node --check app/static/assistant.js
node --check app/static/camera-render.js
```

Python 编译检查：

```bash
PYTHONPATH=. .venv/bin/python -m compileall -q app tests
```

独立测试 JoyAI Voice：

```bash
.venv/bin/python test_voice.py
```

成功后会在项目根目录生成 `voice-test.wav`。

## 日志排查

浏览器 Console 过滤：

```text
ParallelVerse Voice
```

后端 Assistant 日志前缀：

```text
[assistant:<session_id>]
```

常见关键日志：

```text
user transcription completed
assistant route decision route=interaction
Interaction request
Interaction response
connecting to Voice
Voice audio chunk received
Voice synthesis completed
```

完整排障方法见 [`DOCS/06-日志与故障排查.md`](DOCS/06-日志与故障排查.md)。
