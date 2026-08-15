# ParallelVerse

上传和运行时只需要本目录，不依赖目录外的 Python 虚拟环境。

## 目录

```text
Pro/
├── Parallel-core/    # FastAPI 后端及当前页面资源
├── Parallel-panel/   # 独立前端页面文件
└── start.sh          # 统一启动入口
```

## 启动

需要本机安装 Python 3.11 或更高版本。启动脚本会依次查找 `python3.13`、`python3.12`、`python3.11` 和兼容的 `python3`。首次启动会在 `Parallel-core/.venv` 自动创建虚拟环境，并根据 `Parallel-core/requirements.txt` 安装依赖：

首次运行前创建本地配置：

```bash
cp Parallel-core/.env.example Parallel-core/.env
```

然后编辑 `Parallel-core/.env`，填入实际 API Key 和模型地址。真实 `.env` 不应上传到仓库。

```bash
cd Pro
./start.sh
```

项目运行不依赖 `Pro` 目录之外的文件。首次启动需要能够访问配置的 Python 包源。

如果已有 `.venv` 是由 Python 3.10 或更低版本创建，启动脚本会自动删除并使用兼容版本重建。也可以手动指定：

```bash
PYTHON_BIN=python3.11 ./start.sh
```

上传或提交仓库时不要包含以下本机生成文件：

```text
Parallel-core/.env
Parallel-core/.venv/
Parallel-core/voice-test.wav
__pycache__/
.pytest_cache/
```

这些路径已配置在 `.gitignore` 中。

默认监听 `0.0.0.0:8010`，本机访问：

```text
http://127.0.0.1:8010
```

指定端口：

```bash
PORT=8080 ./start.sh
```

详细后端说明见 [`Parallel-core/README.md`](Parallel-core/README.md)。
