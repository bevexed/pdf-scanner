@echo off
python -m venv venv
call venv\Scripts\activate
pip install -r requirements.txt
pyinstaller --noconfirm --onefile --noconsole --name 账单截图导出系统 ^
  --add-data "web;web" ^
  --hidden-import fitz ^
  --hidden-import pystray._win32 ^
  desktop.py
echo 打包完成,exe 在 dist\ 目录下。若客户机白屏,请运行随包 WebView2 安装器。
pause
