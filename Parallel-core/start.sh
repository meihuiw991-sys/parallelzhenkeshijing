#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ -n "${PYTHON_BIN:-}" ]; then
  PYTHON_CANDIDATES=("$PYTHON_BIN")
else
  PYTHON_CANDIDATES=(python3.13 python3.12 python3.11 python3)
fi

PYTHON_BIN=""
for candidate in "${PYTHON_CANDIDATES[@]}"; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
    PYTHON_BIN="$candidate"
    break
  fi
done

if [ -z "$PYTHON_BIN" ]; then
  echo "未找到 Python 3.11 或更高版本。请先安装 Python 3.11+，或通过 PYTHON_BIN 指定解释器。" >&2
  exit 1
fi

echo "使用 Python：$PYTHON_BIN ($("$PYTHON_BIN" -c 'import platform; print(platform.python_version())'))"

if [ -x .venv/bin/python ] && ! .venv/bin/python -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
  echo "检测到现有 .venv 使用 Python 3.10 或更低版本，正在重新创建。"
  rm -rf -- .venv
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
