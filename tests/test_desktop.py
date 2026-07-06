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

def test_flaskserver_shutdown_idempotent():
    srv = desktop.FlaskServer(appmod.app)
    srv.start()
    assert desktop.wait_until_ready(srv.port, timeout=10) is True
    srv.shutdown()
    srv.shutdown()   # 重复调用必须安全无副作用

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
