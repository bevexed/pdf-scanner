# desktop.py
import os, time, threading, urllib.request, urllib.error
import shutil, zipfile
import sys, queue
import app as appmod
from core import config
from werkzeug.serving import make_server


class FlaskServer:
    """用 werkzeug make_server 托管 Flask:自动分配端口 + 优雅 shutdown。"""
    def __init__(self, app):
        # port=0 由 OS 分配空闲端口,一次 bind 无竞态
        self._srv = make_server("127.0.0.1", 0, app, threaded=True)
        self.port = self._srv.server_port
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)
        self._started = False
        self._closed = False

    def start(self):
        self._started = True
        self._thread.start()

    def shutdown(self):
        # 幂等:退出流程可能多次触发
        if self._closed:
            return
        self._closed = True
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


_quitting = False
_window = None
_server = None
_tray = None
_ui_queue = queue.Queue()   # 托盘线程 → UI 调度线程 的动作队列


def post_ui(action, *args):
    """托盘/其他线程投递 UI 动作,由 ui_loop 调度线程执行。"""
    _ui_queue.put((action, args))


# ---- 以下 request_* 只在 ui_loop 调度线程 / pywebview closing 回调 中调用 ----

def request_show():
    _window.show()


def request_quit():
    """真正的退出流程(UI 调度线程执行):导入中先唤回窗口+确认。"""
    global _quitting
    if appmod.is_busy():
        was_hidden = getattr(_window, "hidden", False)
        _window.show()   # 为确认框唤回窗口(托盘退出时窗口通常处于隐藏态)
        ok = _window.create_confirmation_dialog("正在导入", "正在导入,确定退出?中断后需重新导入")
        if not ok:
            if was_hidden:
                _window.hide()   # 取消 = 维持原样:退回隐藏
            return
    # 注意:以下必须同步跑完(尤其 destroy())再返回 ui_loop 的 while 判断。
    # _quitting 置位后本函数仍在 ui_loop 栈内,destroy 一定执行;勿改为异步或挪出。
    _quitting = True
    if _tray is not None:
        _tray.stop()
    if _server is not None:
        _server.shutdown()
    _window.destroy()


def ui_loop():
    """唯一的 UI 调度线程(pywebview 经 webview.start(ui_loop) 放到独立线程运行,
    非主线程):从队列取动作,串行调用 Window API。托盘线程只投递,不碰窗口。"""
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
    """窗口 ✕(pywebview 在主线程触发):✕ = 隐藏窗口,不退出程序。
    - Windows:隐藏到右下角托盘,托盘唤回/退出。
    - macOS:隐藏窗口,从 Dock 图标点击唤回;退出用系统方式(Dock 右键→退出 / Cmd+Q)。
    _quitting 为真时(托盘退出等主动退出路径)才放行真正关闭。"""
    global _quitting
    if _quitting:
        return True
    # macOS 无托盘时,隐藏后靠 Dock 唤回;提示语按平台措辞
    hint_target = "托盘" if _use_tray() else "后台"
    if appmod.is_busy():
        ok = _window.create_confirmation_dialog("正在导入", f"正在导入,确定隐藏到{hint_target}?")
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
    try:
        import pystray
        menu = pystray.Menu(
            pystray.MenuItem("显示", on_tray_show, default=True),
            pystray.MenuItem("退出", on_tray_quit),
        )
        _tray = pystray.Icon("账单截图导出系统", _make_tray_image(), "账单截图导出系统", menu)
        _tray.run()
    except Exception as e:
        # 托盘线程是 daemon,异常会静默终止托盘 → 窗口 ✕ 隐藏后无从唤回。
        # 记录到 stderr,便于打包漏依赖(如 pystray 后端/PIL)时排查。
        sys.stderr.write(f"托盘启动失败,已禁用托盘功能:{e}\n")


def _error_exit(msg):
    """无正常窗口时也让用户看到错误(而非静默白屏/退出)。"""
    sys.stderr.write(msg + "\n")
    try:
        import webview as _wv
        _wv.create_window("启动失败", html=f"<h3 style='font-family:sans-serif'>{msg}</h3>")
        _wv.start()
    except Exception:
        pass


def _use_tray():
    # macOS 首版禁用托盘,规避 AppKit/Cocoa 主循环冲突;Win/Linux 启用
    return sys.platform != "darwin"


def _install_dock_reopen():
    """macOS:点击 Dock 图标时唤回被隐藏的窗口。
    给 pywebview 的 AppDelegate 类补一个 applicationShouldHandleReopen 方法
    (它自身未实现该钩子)。失败则静默降级(仍可用 Cmd+Q / Dock 右键退出,
    仅无法从 Dock 唤回窗口)。"""
    try:
        import objc
        from webview.platforms.cocoa import BrowserView

        def applicationShouldHandleReopen_hasVisibleWindows_(self, app, flag):
            # 点 Dock 图标:投递到 UI 调度线程唤回窗口,不跨线程直接操作窗口
            post_ui("show")
            return True

        objc.classAddMethods(
            BrowserView.AppDelegate,
            [applicationShouldHandleReopen_hasVisibleWindows_],
        )
    except Exception as e:
        sys.stderr.write(f"Dock 唤回未启用(不影响使用,可用 Cmd+Q/Dock 右键退出):{e}\n")


def _safe_export_path(name):
    """把前端给的文件名限制在 EXPORT_DIR 内,防目录穿越;返回真实路径或 None。"""
    name = os.path.basename(name or "")
    if not name:
        return None
    p = os.path.join(config.EXPORT_DIR, name)
    return p if os.path.isfile(p) else None


class Api:
    """暴露给 webview 前端的原生能力:桌面版下载/预览不依赖浏览器 <a> 行为。
    WKWebView(macOS)不支持 <a download>,且 target=_blank 会跳系统浏览器。"""

    def preview(self, name):
        """应用内新开子窗口显示导出的 PNG,不走系统浏览器。"""
        import webview, base64
        p = _safe_export_path(name)
        if not p:
            return {"ok": False, "error": "文件不存在"}
        # 读成 base64 data URI 内嵌:WKWebView 对内联 html 里的 file:// 有安全限制,
        # data URI 不依赖本地文件访问,渲染最稳。
        with open(p, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode("ascii")
        html = (f"<body style='margin:0;background:#222;display:flex;"
                f"align-items:center;justify-content:center;height:100vh'>"
                f"<img src='data:image/png;base64,{b64}' "
                f"style='max-width:100%;max-height:100%'></body>")
        webview.create_window(f"预览 - {name}", html=html, width=900, height=1100)
        return {"ok": True}

    def save_one(self, name):
        """弹原生保存对话框,把单张 PNG 另存到用户选定位置。"""
        p = _safe_export_path(name)
        if not p:
            return {"ok": False, "error": "文件不存在"}
        dest = _window.create_file_dialog(
            appmod_dialog_save(), directory="", save_filename=name)
        if not dest:
            return {"ok": False, "cancelled": True}
        dest = dest if isinstance(dest, str) else dest[0]
        shutil.copyfile(p, dest)
        return {"ok": True, "path": dest}

    def save_zip(self, names):
        """把多张 PNG 打包成 zip,弹原生保存对话框写到用户选定位置。"""
        paths = [(_safe_export_path(n), os.path.basename(n)) for n in (names or [])]
        paths = [(p, n) for p, n in paths if p]
        if not paths:
            return {"ok": False, "error": "无可导出结果"}
        dest = _window.create_file_dialog(
            appmod_dialog_save(), directory="", save_filename="exports.zip")
        if not dest:
            return {"ok": False, "cancelled": True}
        dest = dest if isinstance(dest, str) else dest[0]
        with zipfile.ZipFile(dest, "w") as z:
            for p, n in paths:
                z.write(p, n)
        return {"ok": True, "path": dest, "count": len(paths)}


def appmod_dialog_save():
    """保存对话框类型常量(延迟导入,避免模块级 import webview)。
    新版用 FileDialog.SAVE,老版回退 SAVE_DIALOG。"""
    import webview
    fd = getattr(webview, "FileDialog", None)
    return fd.SAVE if fd is not None else webview.SAVE_DIALOG


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
            width=1200, height=800, js_api=Api(),
        )
        _window.events.closing += on_closing
        # 注入标记:前端据此走原生下载/预览(pywebview.api),而非浏览器 <a> 行为
        _window.events.loaded += lambda: _window.evaluate_js(
            "window.__DESKTOP__ = true")
        if _use_tray():
            threading.Thread(target=_run_tray, daemon=True).start()
        elif sys.platform == "darwin":
            # macOS 无托盘:装 Dock 图标唤回(✕ 隐藏后从 Dock 点回)
            _install_dock_reopen()
        # 主线程跑 GUI 事件循环并阻塞至 destroy;ui_loop 被放到独立线程运行
        webview.start(ui_loop)
    except Exception as e:          # 常见:Win 缺 WebView2 / GUI 初始化失败
        _error_exit(f"窗口创建失败,可能缺少 WebView2 Runtime,请运行随包安装器。\n{e}")
    finally:
        if _tray is not None:
            _tray.stop()
        if _server is not None:
            _server.shutdown()


if __name__ == "__main__":
    # 打包后(PyInstaller 冻结)多进程解析必需:否则子进程会递归重启整个 app
    import multiprocessing
    multiprocessing.freeze_support()
    main()
