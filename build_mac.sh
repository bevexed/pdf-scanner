#!/usr/bin/env bash
set -e
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pyinstaller --noconfirm --windowed --name "账单截图导出系统" \
  --add-data "web:web" \
  --hidden-import fitz \
  desktop.py
echo "打包完成,.app 在 dist/ 目录下"
