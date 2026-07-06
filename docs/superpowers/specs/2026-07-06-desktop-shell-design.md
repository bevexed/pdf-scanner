# 桌面外壳改造设计(原生窗口 + 系统托盘)

日期:2026-07-06
状态:已定稿

## 背景与目标

当前交付形态是 PyInstaller 打包的 Flask 应用:双击 exe 会弹出黑色终端窗口,1 秒后跳转系统浏览器打开 `127.0.0.1:5000`。这不像成品桌面软件——有黑窗、依赖外部浏览器、关掉终端即断服务,客户观感"业余"。

目标:改造成原生桌面窗口的成品软件——**Windows 原生窗口 + 系统托盘;macOS 原生窗口(首版无菜单栏图标)**。**不改任何现有 Flask 路由和业务逻辑**,只在外面套一层桌面外壳。

## 实现边界(硬约束)

- **新增** `desktop.py`(打包唯一入口)
- **微调** `app.py`:`__main__` 只去掉自动 `open_browser`,**保留 `app.run`**(`python app.py` 仍可跑纯 Flask 调试模式,不依赖 pywebview);新增 `is_busy()` 状态查询函数;`_ensure_dirs` 保持模块级可被 import 调用
- **更新依赖**:`requirements.txt` 增加 `pywebview`、`pystray`
- **更新打包入口**:`build_win.bat` 打包目标由 `app.py` 改为 `desktop.py`;新增 `build_mac.sh`
- **不动**:现有 Flask 路由、`core/` 业务处理、`config.py` 的路径逻辑(已正确处理 PyInstaller 冻结场景)

## 架构:外壳与内核分离

```
┌─────────────────────────────────────┐
│  desktop.py  (新增,程序唯一入口)      │
│  1. make_server("127.0.0.1", 0, app) 拿 server + 实际端口 │
│  2. 后台线程 server.serve_forever()   │
│  3. pywebview 原生窗口(主线程 GUI 循环) │
│  4. pystray 托盘(独立线程,仅 Windows) │
│  5. UI 队列调度(ui_loop)+ 退出状态机  │
└─────────────────────────────────────┘
            │ import & 调用(不改业务)
            ▼
┌─────────────────────────────────────┐
│  app.py  (现有 Flask,仅入口/状态微调) │
└─────────────────────────────────────┘
```

开发调试与交付两种模式共存:
- 开发:`python app.py` 直接跑纯 Flask 模式(仅去掉自动开浏览器,`app.run` 保留)
- 交付:打包入口是 `desktop.py`,原生窗口 + 托盘

## 组件设计

### 1. Flask server 生命周期(werkzeug make_server)

不用 `app.run(port=0)` 后台线程 + 猜端口(有端口竞态、无法优雅关闭)。改用 `werkzeug.serving.make_server`,一次拿到 server 对象和实际端口,并支持 `shutdown()`:

```python
from werkzeug.serving import make_server

class FlaskServer:
    def __init__(self, app):
        # port=0 让 OS 分配空闲端口,无 close-再-bind 竞态窗口
        self._srv = make_server("127.0.0.1", 0, app, threaded=True)
        self.port = self._srv.server_port
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)
        self._started = False
        self._closed = False          # 幂等标记

    def start(self):
        self._started = True
        self._thread.start()

    def shutdown(self):
        if self._closed:              # 幂等:退出流程可能多次触发
            return
        self._closed = True
        if self._started:
            self._srv.shutdown()      # 优雅停(仅在 serve_forever 运行时)
            self._thread.join(timeout=5)
        else:
            self._srv.server_close()  # 未 start:只关 socket,避免 shutdown 死锁
```

`make_server` 内部一次性 `socket.bind`,拿到的 `server_port` 就是已占用的真实端口,消除"先拿端口再 close 再让 Flask 重新 bind"的竞态。

启动前调用 `app._ensure_dirs()`(建目录 + 初始化 DB)。窗口打开前轮询 `http://127.0.0.1:{port}/` 直到 200(超时上限 10s),避免竞态白屏。

### 2. 线程模型 + UI 队列调度(关键,macOS 敏感)

线程归属:

- **pywebview GUI 事件循环在主线程**运行(`webview.start()` 阻塞主线程,macOS 上 GUI 必须主线程,硬约束)。
- **Flask server** 在 daemon 后台线程(见上)。
- **pystray 托盘** 在**独立 daemon 线程**运行(`icon.run()` 是阻塞循环)。
- **UI 调度线程 `ui_loop`**:经 `webview.start(ui_loop)` 启动。**注意 pywebview 会把该 func 放到独立线程运行(不是主线程)**;它是**唯一串行调用 Window API 的线程**。

**跨线程窗口操作策略(核心):托盘回调线程绝不直接操作窗口对象**,只通过 `queue.Queue` 投递动作;由唯一的 `ui_loop` 取出并串行调用 `show()`/`hide()`/`create_confirmation_dialog()`/`destroy()`。这样任一时刻只有一个线程碰窗口,规避 pywebview 多线程并发操作的跨平台风险(macOS 尤敏感)。

```python
_ui_queue = queue.Queue()

def post_ui(action, *args):        # 任意线程(如托盘)调用,只投递
    _ui_queue.put((action, args))

def ui_loop():                     # 唯一 UI 调度线程,串行执行窗口方法
    while not _quitting:
        try:
            action, args = _ui_queue.get(timeout=0.1)
        except queue.Empty:
            continue
        if action == "show":
            request_show()
        elif action == "quit":
            request_quit()
```

启动顺序:
1. 主线程:`_ensure_dirs()` → `FlaskServer.start()` → `wait_until_ready`
2. 主线程:起 pystray 托盘线程(daemon,仅 Windows;macOS 首版不起,见跨平台差异)
3. 主线程:`webview.create_window(...)` + `webview.start(ui_loop)`(GUI 循环阻塞主线程;`ui_loop` 在独立线程调度 UI)

### 3. 原生窗口(pywebview)

```python
import webview
window = webview.create_window("账单截图导出系统",
                               f"http://127.0.0.1:{port}", width=1200, height=800)
window.events.closing += on_closing   # 见状态机
webview.start(ui_loop)   # 主线程跑 GUI 循环并阻塞;ui_loop 被放到独立线程调度 UI
```

内核:pywebview 默认使用系统内核 —— Windows 用 Edge WebView2,macOS 用系统 WebKit。**不内置 Chromium**(CEF Python 长期缺维护、PyInstaller 打包坑多,与"稳定交付"目标冲突)。

### 4. 状态查询(is_busy)

`app.py` 新增:

```python
def is_busy():
    """导入进行中(供桌面外壳判断是否可安全退出)。"""
    return _progress["state"] == "parsing"
```

桌面层只调 `is_busy()`,不直接理解 `_progress` 内部字符串。

### 5. 退出 / 隐藏状态机

用一个模块级退出标记 `_quitting` 区分"隐藏"与"真退出",避免托盘退出时又被关窗拦截。

**窗口 ✕(`closing` 事件)**:
```python
_quitting = False

def on_closing():
    if _quitting:
        return True                    # 放行,真正关闭
    if is_busy():
        ok = window.create_confirmation_dialog("正在导入", "正在导入,确定隐藏到托盘?")
        if not ok:
            return False               # 取消:不隐藏,窗口保持可见
    window.hide()                      # 确认(或非导入中)才隐藏
    return False                       # 取消默认关闭 → 隐藏到托盘
```
返回 `False` 取消 pywebview 默认关闭。导入中弹确认框:确认才 `window.hide()`,取消则窗口保持可见、不隐藏。非导入中直接隐藏。返回 `True`(仅 `_quitting` 时)才真正销毁窗口。

**托盘回调(运行在 pystray 线程):只投递,不碰窗口**:
```python
def on_tray_show(icon=None, item=None):
    post_ui("show")

def on_tray_quit(icon=None, item=None):
    post_ui("quit")
```

**真正的 UI 动作在 `ui_loop` 线程执行**(`request_show`/`request_quit`):
```python
def request_show():
    window.show()

def request_quit():
    global _quitting
    if is_busy():
        window.show()                  # 先唤回窗口,提供确认上下文
        ok = window.create_confirmation_dialog("正在导入", "正在导入,确定退出?中断后需重新导入")
        if not ok:
            return                      # 取消:不退出
    _quitting = True
    if tray is not None:
        tray.stop()                    # 停托盘线程
    server.shutdown()                  # 幂等,优雅停 Flask
    window.destroy()                   # 触发 closing→_quitting=True→放行→webview.start() 返回
```
托盘退出的确认必须用 `window.create_confirmation_dialog`(真确认),不能用 pystray notify(仅通知、无返回值)。`server.shutdown()` 做成**幂等**(`_closed` 标记):退出流程可能被 `request_quit`、`main()` 的 `finally`、`on_closing` 多次触发,重复调用必须无副作用。

状态迁移:
```
[有托盘/Windows]
运行中 --✕--> 隐藏到托盘(进程存活) --托盘"显示"(post_ui show)--> 运行中
运行中/隐藏 --托盘"退出"(post_ui quit)--> [is_busy? 二次确认] --> _quitting=True → 全部 shutdown → 进程结束

[无托盘/macOS 首版]
运行中 --✕--> [is_busy? 退出确认] --> _quitting=True → shutdown → 进程结束
```

导入中断安全性:`indexer` 采用批次事务(`begin_batch`/`commit_batch`/`fail_batch`),`insert_tickets` 分批写 SQLite。进程被强杀时可能留下 pending 批次和半成品行,但**不会污染可见查询结果**(未 commit 的批次查询不可见);**同 hash 重新导入会清理该文件的 pending 数据**。故中断可安全恢复,重新导入即可。

## 跨平台差异(已知限制)

- **Windows**:托盘图标在右下角,✕→隐藏→托盘唤回符合 Windows 肌肉记忆,体验自然。启动时若 pywebview 创建失败(通常是缺 **Edge WebView2 Runtime**),**捕获异常并弹明确错误对话框**:"缺少 WebView2 Runtime,请运行随包安装器"——不让客户面对不可诊断的白屏。交付包附带 WebView2 bootstrapper 安装器。
- **macOS**:无"系统托盘",对应顶部菜单栏图标(status bar item)。由于 pystray(AppKit)与 pywebview(Cocoa)主循环共存存在冲突风险,**首版 macOS 直接不启用托盘/菜单栏图标**(`_use_tray()` 返回 `False`),窗口 ✕ 即退出程序(导入中二次确认),优先保证窗口稳定与可打包交付。菜单栏图标作为后续增强项,记为已知限制。macOS 用系统 WebKit,真·零额外依赖。

## 打包

- **Windows**:`build_win.bat` 打包目标 `app.py` → `desktop.py`;`--noconsole` 去黑窗;保留 `--add-data "web;web"`、`--hidden-import fitz`,补 pywebview/pystray 相关 hidden import。交付包附带 WebView2 安装器。
- **macOS**:新增 `build_mac.sh`,产出 `.app` bundle(`--windowed`),配图标 `.icns`,`--add-data "web:web"`(Mac 用冒号分隔)。

## 依赖变更

`requirements.txt` 新增:
```
pywebview
pystray
```

## 错误处理

- Flask 启动超时(10s 内 `/` 不返回 200):弹错误对话框并退出,不静默白屏。
- pywebview 窗口创建失败(Win 缺 WebView2):捕获异常 → 明确错误对话框指向随包安装器。

## 测试

- 单元:`is_busy()` 在各 `_progress["state"]` 下返回正确布尔;`FlaskServer` 能拿到有效端口、`serve_forever`/`shutdown` 正常、未 start 安全 close、shutdown 幂等。
- 手动:
  - macOS(`python desktop.py`,首版无托盘):验证原生窗口、✕ 退出、导入中退出确认。
  - Windows(打包 exe 后):验证托盘、✕ 隐藏、托盘显示/退出、导入中确认、缺 WebView2 时的错误对话框。
- 回归:现有 pytest 全绿(业务未动,应无影响)。

## 非目标(YAGNI)

- 不上 waitress/gunicorn(首版本地壳,dev server 仅绑 127.0.0.1 足够;已用 make_server 拿到优雅 shutdown)。
- 不做单实例锁(pywebview 单窗 + 自动端口,双开顶多多一窗,无抢端口崩溃)。
- 不内置 Chromium。
