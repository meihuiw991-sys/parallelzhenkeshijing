#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "未找到 Python：$PYTHON_BIN，请先安装 Python 3.11 或更高版本。" >&2
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "首次启动：正在创建本地虚拟环境 .venv"
  "$PYTHON_BIN" -m venv .venv
fi

INSTALL_MARKER=".venv/.parallelverse-installed"

if [ ! -x .venv/bin/uvicorn ] || [ ! -f "$INSTALL_MARKER" ] || [ requirements.txt -nt "$INSTALL_MARKER" ]; then
  echo "正在安装或更新项目依赖"
  .venv/bin/python -m pip install -r requirements.txt
  touch "$INSTALL_MARKER"
fi

exec .venv/bin/uvicorn \
  app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8010}"
