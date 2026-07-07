#!/usr/bin/env bash
# macOS 打包脚本:复用已有 venv,缺失时才创建;全程用 venv 内解释器,
# 不受外部 `python3` 指向哪个版本影响(避免 3.14 等新版 ensurepip 失败)。
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x venv/bin/python ]; then
  echo "未找到 venv,正在创建..."
  python3 -m venv venv
fi

VENV_PY=venv/bin/python
"$VENV_PY" -m pip install --upgrade pip >/dev/null
"$VENV_PY" -m pip install -r requirements.txt

rm -rf build "dist/账单截图导出系统.app"
"$VENV_PY" -m PyInstaller --noconfirm --windowed --name "账单截图导出系统" \
  --add-data "web:web" \
  --hidden-import fitz \
  --hidden-import pystray._darwin \
  desktop.py

echo "✅ 打包完成:dist/账单截图导出系统.app"
