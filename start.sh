#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

exec ./Parallel-core/start.sh
