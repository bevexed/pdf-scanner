@echo off
python -m venv venv
call venv\Scripts\activate
pip install -r requirements.txt
pyinstaller --noconfirm --onefile --name 账单截图导出系统 ^
  --add-data "web;web" --hidden-import fitz app.py
echo 打包完成,exe 在 dist\ 目录下
pause
