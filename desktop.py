# desktop.py
import time, threading, urllib.request, urllib.error
import sys, queue
import app as appmod
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
    """窗口 ✕(pywebview 在主线程触发):导入中确认才隐藏;否则隐藏到托盘。"""
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
    main()
