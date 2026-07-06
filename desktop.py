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
