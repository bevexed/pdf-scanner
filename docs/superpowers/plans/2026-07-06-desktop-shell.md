# 桌面外壳(原生窗口 + 系统托盘)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Flask+浏览器交付形态改造成原生桌面窗口 + 系统托盘的成品软件,跨 Windows/macOS,不改现有 Flask 路由与业务。

**Architecture:** 外壳与内核分离。新增 `desktop.py` 作打包唯一入口:用 `werkzeug.serving.make_server` 在后台 daemon 线程跑 Flask(自动分配端口、支持优雅 shutdown),pywebview 在主线程开原生窗口连该端口,pystray 在独立 daemon 线程提供托盘。**托盘回调线程不直接操作窗口**:通过 `queue.Queue` 投递动作,由 pywebview 主线程的 `ui_loop` 调度执行所有窗口方法(show/hide/confirm/destroy),规避跨线程 GUI 风险(macOS 敏感)。`app.py` 仅微调入口并新增 `is_busy()`。

**Tech Stack:** Flask(现有)、werkzeug.make_server、pywebview(系统 WebView2/WebKit 内核)、pystray、PyInstaller。

**设计依据:** [docs/superpowers/specs/2026-07-06-desktop-shell-design.md](../specs/2026-07-06-desktop-shell-design.md)

---

## 文件结构

| 文件 | 责任 | 动作 |
|---|---|---|
| `app.py` | Flask 业务(现有)。`__main__` 去掉 `open_browser`;新增 `is_busy()` | 修改 |
| `desktop.py` | 桌面壳入口:Flask 生命周期、窗口、托盘、UI 队列调度、退出状态机 | 新增 |
| `desktop.py` 内 `FlaskServer` 类 | 封装 make_server + serve_forever + shutdown(未 start 安全 close) | 新增 |
| `requirements.txt` | 加 pywebview、pystray | 修改 |
| `build_win.bat` | 打包入口 app.py→desktop.py,加 --noconsole | 修改 |
| `build_mac.sh` | macOS .app 打包 | 新增 |
| `tests/test_app.py` | 加 `is_busy()` 测试(fixture 恢复状态) | 修改 |
| `tests/test_desktop.py` | `FlaskServer` 启停/端口/未 start 安全 close 测试 | 新增 |

**测试边界(诚实声明):** pywebview 窗口、pystray 托盘、`create_confirmation_dialog`、`ui_loop` 依赖真实 GUI event loop,无头环境不可自动化。故**自动化测试仅覆盖纯逻辑**(`is_busy()`、`FlaskServer` 启停与端口、未 start 安全 close);窗口/托盘/关窗隐藏/退出确认/UI 队列调度列入 Task 8 的**手动验证清单**。

**GUI 库懒加载约定:** `webview`、`pystray`、`PIL` **不在 desktop.py 顶层 import**,只在 GUI 函数内部 import。这样 `tests/test_desktop.py` 仅测 `FlaskServer` 时,即使环境缺 GUI 系统库也不会因 `import desktop` 失败。

---

## Task 1: app.py 去掉自动开浏览器 + 新增 is_busy()

**Files:**
- Modify: `app.py:2`(import)、`app.py:13` 后(加 `is_busy`)、`app.py:128-134`(`__main__` + 删 `open_browser`)
- Test: `tests/test_app.py`

- [ ] **Step 1: 写失败测试(带状态恢复 fixture)**

在 `tests/test_app.py` 顶部 `import app as appmod` 之后加一个自动恢复 `_progress` 的 fixture,再追加用例:

```python
import pytest

@pytest.fixture
def restore_progress():
    saved = dict(appmod._progress)
    yield
    appmod._progress = saved

def test_is_busy_true_when_parsing(restore_progress):
    appmod._progress = {"state": "parsing", "done": 0, "total": 10, "tickets": 0, "message": ""}
    assert appmod.is_busy() is True

def test_is_busy_false_when_idle(restore_progress):
    appmod._progress = {"state": "idle", "done": 0, "total": 0, "tickets": 0, "message": ""}
    assert appmod.is_busy() is False

def test_is_busy_false_when_done(restore_progress):
    appmod._progress = {"state": "done", "done": 10, "total": 10, "tickets": 5, "message": ""}
    assert appmod.is_busy() is False
```

> fixture 用 try/finally 语义(`yield` 后恢复),避免改 `_progress` 污染后续用例。

- [ ] **Step 2: 运行确认失败**

Run: `venv/bin/python -m pytest tests/test_app.py::test_is_busy_true_when_parsing -v`
Expected: FAIL,`AttributeError: module 'app' has no attribute 'is_busy'`

- [ ] **Step 3: 实现 is_busy()**

在 `app.py` 的 `_REQUIRED_MASK` 定义之后(约 line 13 后)加:

```python
def is_busy():
    """导入进行中(供桌面外壳判断是否可安全退出)。"""
    return _progress["state"] == "parsing"
```

- [ ] **Step 4: 去掉 __main__ 里的自动开浏览器**

`app.py` 顶部第 2 行去掉 `webbrowser`:
`import os, threading, webbrowser, zipfile, io` → `import os, threading, zipfile, io`

删除 `open_browser` 函数(原 line 128-129),并把结尾 `__main__` 改为:

```python
if __name__ == "__main__":
    _ensure_dirs()
    app.run(host="127.0.0.1", port=5000)
```

- [ ] **Step 5: 运行测试确认通过 + 回归**

Run: `venv/bin/python -m pytest tests/test_app.py -v`
Expected: 全部 PASS(含新 3 个与原有用例)

- [ ] **Step 6: 提交**

```bash
git add app.py tests/test_app.py
git commit -m "feat: app.py 新增 is_busy() 并移除自动开浏览器"
```

---

## Task 2: 安装桌面壳依赖

**Files:**
- Modify: `requirements.txt`

> **网络备注:** 本 Task 需联网装包。若执行环境网络受限,需先申请审批或改用离线 wheel(`pip install --no-index --find-links=<离线目录>`)。macOS 上 pywebview 会拉 pyobjc 系列,包较多。

- [ ] **Step 1: 追加依赖**

在 `requirements.txt` 末尾加两行:

```
pywebview>=5.0
pystray>=0.19
```

- [ ] **Step 2: 安装**

Run: `venv/bin/pip install -r requirements.txt`
Expected: 成功安装 pywebview、pystray 及平台依赖

- [ ] **Step 3: 验证可导入**

Run: `venv/bin/python -c "import webview, pystray; print('ok')"`
Expected: 打印 `ok`

- [ ] **Step 4: 提交**

```bash
git add requirements.txt
git commit -m "chore: 增加桌面壳依赖 pywebview/pystray"
```

---

## Task 3: FlaskServer 生命周期封装(TDD)

**Files:**
- Create: `desktop.py`
- Test: `tests/test_desktop.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_desktop.py`,覆盖:分配端口、能服务 index、**未 start 也能安全 shutdown**、死端口超时:

```python
# tests/test_desktop.py
import os, tempfile, urllib.request
import core.config as _cfg
_cfg.DATA_DIR = tempfile.mkdtemp()
_cfg.DB_PATH = os.path.join(_cfg.DATA_DIR, "t.db")
_cfg.PDF_DIR = os.path.join(_cfg.DATA_DIR, "pdfs")
_cfg.EXPORT_DIR = os.path.join(_cfg.DATA_DIR, "exports")
os.makedirs(_cfg.PDF_DIR, exist_ok=True); os.makedirs(_cfg.EXPORT_DIR, exist_ok=True)

import app as appmod
appmod._ensure_dirs()
import desktop

def test_flaskserver_assigns_port():
    srv = desktop.FlaskServer(appmod.app)
    assert isinstance(srv.port, int) and srv.port > 0
    srv.shutdown()   # 未 start,必须能安全返回(不阻塞)

def test_flaskserver_shutdown_without_start_is_safe():
    srv = desktop.FlaskServer(appmod.app)
    srv.shutdown()   # 关键:未 serve_forever 时 shutdown 不能死锁

def test_flaskserver_serves_index():
    srv = desktop.FlaskServer(appmod.app)
    srv.start()
    try:
        assert desktop.wait_until_ready(srv.port, timeout=10) is True
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.port}/") as r:
            assert r.status == 200
    finally:
        srv.shutdown()

def test_wait_until_ready_times_out_on_dead_port():
    assert desktop.wait_until_ready(1, timeout=1) is False
```

- [ ] **Step 2: 运行确认失败**

Run: `venv/bin/python -m pytest tests/test_desktop.py -v`
Expected: FAIL,`ModuleNotFoundError: No module named 'desktop'`

- [ ] **Step 3: 创建 desktop.py 的 FlaskServer + wait_until_ready**

创建 `desktop.py`,先只放这两部分(GUI 部分 Task 4 再加)。**顶层不 import GUI 库**:

```python
# desktop.py
import time, threading, urllib.request, urllib.error
from werkzeug.serving import make_server


class FlaskServer:
    """用 werkzeug make_server 托管 Flask:自动分配端口 + 优雅 shutdown。"""
    def __init__(self, app):
        # port=0 由 OS 分配空闲端口,一次 bind 无竞态
        self._srv = make_server("127.0.0.1", 0, app, threaded=True)
        self.port = self._srv.server_port
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)
        self._started = False

    def start(self):
        self._started = True
        self._thread.start()

    def shutdown(self):
        # serve_forever 未运行时调 shutdown() 会阻塞;未 start 只 close socket
        if self._started:
            self._srv.shutdown()
            self._thread.join(timeout=5)
        else:
            self._srv.server_close()


def wait_until_ready(port, timeout=10.0):
    """轮询 http://127.0.0.1:{port}/ 直到 200 或超时。返回是否就绪。"""
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.1)
    return False
```

- [ ] **Step 4: 运行测试确认通过**

Run: `venv/bin/python -m pytest tests/test_desktop.py -v`
Expected: 4 个用例全 PASS(尤其 `shutdown_without_start` 不卡死)

- [ ] **Step 5: 提交**

```bash
git add desktop.py tests/test_desktop.py
git commit -m "feat: desktop.py FlaskServer(未start安全close) + wait_until_ready"
```

---

## Task 4: 窗口 + UI 队列调度 + 退出状态机(GUI,非自动测)

**Files:**
- Modify: `desktop.py`

> 本 Task 依赖真实 GUI event loop,不写自动化测试;正确性由 Task 8 手动清单验证。
> **核心:托盘回调线程只 `post_ui(...)` 投递,绝不直接碰 `_window`。** 所有窗口方法(show/hide/confirm/destroy)由主线程 `ui_loop` 执行。GUI 库全部函数内懒加载。

- [ ] **Step 1: 加 UI 队列、窗口、托盘、状态机与 main()**

在 `desktop.py` **顶层 import 只加 `queue` 和 `sys`**(GUI 库不上顶层):

```python
import sys, queue
import app as appmod
```

在文件末尾追加:

```python
_quitting = False
_window = None
_server = None
_tray = None
_ui_queue = queue.Queue()   # 托盘线程 → 主线程 的动作队列


def post_ui(action, *args):
    """托盘/其他线程投递 UI 动作,由主线程 ui_loop 执行。"""
    _ui_queue.put((action, args))


# ---- 以下 request_* 只在主线程(ui_loop / closing 回调)里被调用 ----

def request_show():
    _window.show()


def request_quit():
    """真正的退出流程(主线程执行):导入中先唤回窗口+确认。"""
    global _quitting
    if appmod.is_busy():
        _window.show()
        ok = _window.create_confirmation_dialog("正在导入", "正在导入,确定退出?中断后需重新导入")
        if not ok:
            return
    _quitting = True
    if _tray is not None:
        _tray.stop()
    if _server is not None:
        _server.shutdown()
    _window.destroy()


def ui_loop():
    """pywebview 主线程循环:从队列取动作并在主线程执行窗口方法。"""
    while not _quitting:
        try:
            action, args = _ui_queue.get(timeout=0.1)
        except queue.Empty:
            continue
        if action == "show":
            request_show()
        elif action == "quit":
            request_quit()


def on_closing():
    """窗口 ✕(pywebview 在主线程触发):导入中确认才隐藏;否则隐藏到托盘。"""
    global _quitting
    if _quitting:
        return True
    if appmod.is_busy():
        ok = _window.create_confirmation_dialog("正在导入", "正在导入,确定隐藏到托盘?")
        if not ok:
            return False           # 取消:窗口保持可见
    _window.hide()
    return False                   # 取消默认关闭 → 隐藏


# ---- 托盘回调:运行在 pystray 线程,只投递,不碰窗口 ----

def on_tray_show(icon=None, item=None):
    post_ui("show")


def on_tray_quit(icon=None, item=None):
    post_ui("quit")


def _make_tray_image():
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (64, 64), (30, 30, 30))
    d = ImageDraw.Draw(img)
    d.rectangle([12, 12, 52, 52], outline=(230, 230, 230), width=3)
    return img


def _run_tray():
    global _tray
    import pystray
    menu = pystray.Menu(
        pystray.MenuItem("显示", on_tray_show, default=True),
        pystray.MenuItem("退出", on_tray_quit),
    )
    _tray = pystray.Icon("账单截图导出系统", _make_tray_image(), "账单截图导出系统", menu)
    _tray.run()


def _error_exit(msg):
    """无正常窗口时也让用户看到错误(而非静默白屏/退出)。"""
    sys.stderr.write(msg + "\n")
    try:
        import webview as _wv
        _wv.create_window("启动失败", html=f"<h3 style='font-family:sans-serif'>{msg}</h3>")
        _wv.start()
    except Exception:
        pass


def main():
    global _window, _server
    import webview
    appmod._ensure_dirs()
    _server = FlaskServer(appmod.app)
    _server.start()
    if not wait_until_ready(_server.port):
        _server.shutdown()
        _error_exit("服务启动超时,请重试")
        return
    try:
        _window = webview.create_window(
            "账单截图导出系统", f"http://127.0.0.1:{_server.port}",
            width=1200, height=800,
        )
        _window.events.closing += on_closing
        if _use_tray():
            threading.Thread(target=_run_tray, daemon=True).start()
        webview.start(ui_loop)     # 主线程跑 ui_loop,阻塞至 destroy
    except Exception as e:          # 常见:Win 缺 WebView2 / GUI 初始化失败
        _error_exit(f"窗口创建失败,可能缺少 WebView2 Runtime,请运行随包安装器。\n{e}")
    finally:
        if _tray is not None:
            _tray.stop()
        if _server is not None:
            _server.shutdown()


if __name__ == "__main__":
    main()
```

> 注:`threading` 已在 Task 3 顶层 import;`_use_tray()` 在 Task 4b 定义(本 Task 先加一个恒为 True 的临时桩,Task 4b 再替换)。临时桩:
> ```python
> def _use_tray():
>     return True
> ```

- [ ] **Step 2: 回归自动化测试(确保新增未破坏 FlaskServer 且不引入 GUI 顶层依赖)**

Run: `venv/bin/python -m pytest tests/test_desktop.py tests/test_app.py -v`
Expected: 全 PASS。`import desktop` 不触发 GUI 库 import(懒加载),`main()` 未被调用。

- [ ] **Step 3: 提交**

```bash
git add desktop.py
git commit -m "feat: desktop.py 窗口+UI队列调度+退出隐藏状态机(托盘线程不碰窗口)"
```

---

## Task 4b: macOS 托盘退化(平台分支)

**Files:**
- Modify: `desktop.py`

> 设计已定:若 macOS 上 pystray(AppKit)与 pywebview(Cocoa)主循环冲突,首版**去托盘**,窗口 ✕ 改为退出确认。用平台判断落地为可开关的 `_use_tray()`,并让 `on_closing` 在无托盘时走退出语义。

- [ ] **Step 1: 用平台判断替换临时桩**

把 Task 4 里临时的 `_use_tray()` 替换为:

```python
def _use_tray():
    # macOS 首版禁用托盘,规避 AppKit/Cocoa 主循环冲突;Win/Linux 启用
    return sys.platform != "darwin"
```

- [ ] **Step 2: on_closing 在无托盘时走退出确认**

修改 `on_closing`,开头加无托盘分支(无托盘时 ✕ 不能"隐藏到托盘",否则用户无法找回窗口):

```python
def on_closing():
    global _quitting
    if _quitting:
        return True
    if not _use_tray():
        # 无托盘(macOS 首版):✕ = 退出,导入中确认
        if appmod.is_busy():
            ok = _window.create_confirmation_dialog("正在导入", "正在导入,确定退出?中断后需重新导入")
            if not ok:
                return False
        _quitting = True
        if _server is not None:
            _server.shutdown()
        return True                # 放行关闭 → webview.start 返回
    # 有托盘:✕ = 隐藏
    if appmod.is_busy():
        ok = _window.create_confirmation_dialog("正在导入", "正在导入,确定隐藏到托盘?")
        if not ok:
            return False
    _window.hide()
    return False
```

- [ ] **Step 3: 回归测试**

Run: `venv/bin/python -m pytest tests/test_desktop.py tests/test_app.py -v`
Expected: 全 PASS(纯逻辑不受平台分支影响)

- [ ] **Step 4: 提交**

```bash
git add desktop.py
git commit -m "feat: macOS 首版禁用托盘,✕ 走退出确认(平台分支)"
```

---

## Task 5: Windows 打包脚本

**Files:**
- Modify: `build_win.bat`

- [ ] **Step 1: 改打包入口与参数**

把 `build_win.bat` 内容整体替换为:

```bat
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
```

要点:入口 `desktop.py`;`--noconsole` 去黑窗;`pystray._win32` hidden import(PyInstaller 常漏 pystray 平台后端)。

- [ ] **Step 2: 提交**

```bash
git add build_win.bat
git commit -m "build: Windows 打包改入口 desktop.py + noconsole"
```

> 出 exe 需在 Windows 机器跑本脚本;macOS 上无法产 Windows exe。exe 验证归 Task 8。

---

## Task 6: macOS 打包脚本

**Files:**
- Create: `build_mac.sh`

- [ ] **Step 1: 创建 build_mac.sh**

```bash
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
```

要点:`--windowed` 产 .app;`--add-data` 用冒号 `web:web`;macOS 首版无托盘(见 Task 4b)故不必带 pystray hidden import。图标 `.icns` 首版省略。

- [ ] **Step 2: 赋可执行位**

Run: `chmod +x build_mac.sh`

- [ ] **Step 3: 提交**

```bash
git add build_mac.sh
git commit -m "build: 新增 macOS 打包脚本 build_mac.sh"
```

---

## Task 7: 交付文档更新

**Files:**
- Modify: `docs/账单截图导出系统_实施文档.md`

- [ ] **Step 1: 追加桌面版说明(含平台差异)**

在实施文档运行方式章节追加:

```markdown
## 桌面版(推荐交付形态)

双击「账单截图导出系统」即打开独立窗口,无终端、无需浏览器。

**Windows**
- 关闭窗口(✕):隐藏到右下角系统托盘,程序继续后台运行。
- 托盘图标右键:「显示」恢复窗口,「退出」关闭程序;导入进行中退出会二次确认。
- 白屏:极少数老机器缺 Edge WebView2 Runtime,请双击随包 `WebView2 安装器` 安装后重开。

**macOS**
- 首版无菜单栏图标:关闭窗口(✕)即退出程序;导入进行中会二次确认。
- 系统自带 WebKit,无需额外安装。

**数据位置:** 与程序同目录的 `data/` 文件夹(账单库、导出图)。中断导入不污染已入库数据,重新导入即可。
```

- [ ] **Step 2: 提交**

```bash
git add docs/账单截图导出系统_实施文档.md
git commit -m "docs: 交付文档补桌面版使用、平台差异与 WebView2 说明"
```

---

## Task 8: 手动验证清单(GUI 交互,人工执行)

**Files:** 无(执行验证,记录结果)

不产生代码提交。执行者逐项验证并勾选:

**macOS 本机(`venv/bin/python desktop.py`,首版无托盘):**
- [ ] 启动出现原生窗口,标题「账单截图导出系统」,无终端黑窗、无系统浏览器弹出
- [ ] 界面功能正常(导入一个小 PDF、查询、导出图片可见)
- [ ] 点窗口 ✕ → 程序退出(无托盘)
- [ ] 导入进行中点 ✕ → 弹「确定退出?」;取消 → 窗口保持;确认 → 退出
- [ ] `venv/bin/python -m pytest -v` 全绿

**Windows(打包 exe 后,有托盘):**
- [ ] 双击 exe → 原生窗口,无黑窗、无浏览器
- [ ] ✕ → 隐藏到右下角托盘;托盘「显示」恢复;「退出」关闭
- [ ] 导入中 ✕ → 弹「隐藏到托盘?」确认;导入中托盘「退出」→ 先唤回窗口 + 弹「退出?」确认
- [ ] 托盘「退出」后进程真正结束(任务管理器无残留)
- [ ] 无 WebView2 的机器(或临时卸载)→ 弹「缺少 WebView2 Runtime…」错误窗,非白屏
- [ ] 装 WebView2 安装器后重开 → 正常

**跨线程回归重点(Windows):**
- [ ] 从托盘「显示」/「退出」触发的窗口操作均正常(验证 UI 队列调度生效,无跨线程崩溃)

---

## 完成标准

- 自动化:`pytest` 全绿(`is_busy()` 3 例、`FlaskServer`/`wait_until_ready` 4 例含未 start 安全 close、原有用例)。
- 手动:Task 8 清单 macOS 段全部通过;Windows 段在有 Win 环境时通过。
- 交付:`desktop.py` 为打包入口,产物无黑窗、无外部浏览器依赖;文档含平台差异与 WebView2 兜底。
