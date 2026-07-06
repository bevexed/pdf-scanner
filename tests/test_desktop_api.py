# tests/test_desktop_api.py
"""桌面版原生下载/预览 Api 的回归测试。
GUI 部分(保存对话框、预览子窗口)用打桩替身,不弹真实窗口。"""
import os, zipfile, pytest
import desktop
from core import config


@pytest.fixture
def export_dir(tmp_path, monkeypatch):
    """把 EXPORT_DIR 指向临时目录,放一张假 PNG。"""
    d = tmp_path / "exports"
    d.mkdir()
    png = d / "889635416339_5.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
    monkeypatch.setattr(config, "EXPORT_DIR", str(d))
    return d


class FakeWindow:
    """替身窗口:记录 create_file_dialog 调用,返回预设的目标路径。"""
    def __init__(self, dest):
        self._dest = dest
        self.calls = []

    def create_file_dialog(self, dialog_type, **kw):
        self.calls.append((dialog_type, kw))
        return self._dest


# ---- _safe_export_path:目录穿越防护 ----

def test_safe_path_returns_existing_file(export_dir):
    p = desktop._safe_export_path("889635416339_5.png")
    assert p == str(export_dir / "889635416339_5.png")

def test_safe_path_rejects_traversal(export_dir, tmp_path):
    # 穿越指向 EXPORT_DIR 之外真实存在的文件,仍必须被挡下(basename 归一)
    outside = tmp_path / "secret.txt"
    outside.write_text("x")
    rel = os.path.join("..", "secret.txt")   # 从 exports/ 穿越到上级的真实文件
    assert desktop._safe_export_path(rel) is None

def test_safe_path_rejects_empty(export_dir):
    assert desktop._safe_export_path("") is None
    assert desktop._safe_export_path(None) is None

def test_safe_path_missing_file_is_none(export_dir):
    assert desktop._safe_export_path("nope.png") is None


# ---- save_one:单张另存 ----

def test_save_one_copies_to_chosen_path(export_dir, tmp_path, monkeypatch):
    dest = str(tmp_path / "saved.png")
    monkeypatch.setattr(desktop, "_window", FakeWindow(dest))
    r = desktop.Api().save_one("889635416339_5.png")
    assert r["ok"] is True and r["path"] == dest
    assert os.path.isfile(dest)

def test_save_one_cancelled(export_dir, monkeypatch):
    monkeypatch.setattr(desktop, "_window", FakeWindow(None))  # 用户取消
    r = desktop.Api().save_one("889635416339_5.png")
    assert r == {"ok": False, "cancelled": True}

def test_save_one_missing_file(export_dir, monkeypatch):
    monkeypatch.setattr(desktop, "_window", FakeWindow("/x/y.png"))
    r = desktop.Api().save_one("nope.png")
    assert r["ok"] is False and "不存在" in r["error"]

def test_save_one_handles_list_dialog_return(export_dir, tmp_path, monkeypatch):
    # 某些平台 create_file_dialog 返回元组/列表,取第一项
    dest = str(tmp_path / "saved.png")
    monkeypatch.setattr(desktop, "_window", FakeWindow((dest,)))
    r = desktop.Api().save_one("889635416339_5.png")
    assert r["ok"] is True and os.path.isfile(dest)


# ---- preview:应用内子窗口显示 ----

def test_preview_embeds_base64_not_file_url(export_dir, monkeypatch):
    # WKWebView 里内联 html 的 file:// 加载不出来(黑屏),必须内嵌 data URI
    import webview, base64
    captured = {}
    def fake_create_window(title, html=None, **kw):
        captured["title"] = title
        captured["html"] = html
    monkeypatch.setattr(webview, "create_window", fake_create_window)
    r = desktop.Api().preview("889635416339_5.png")
    assert r["ok"] is True
    assert "file://" not in captured["html"]
    raw = (export_dir / "889635416339_5.png").read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    assert f"data:image/png;base64,{b64}" in captured["html"]

def test_preview_missing_file(export_dir, monkeypatch):
    import webview
    called = {"n": 0}
    monkeypatch.setattr(webview, "create_window",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    r = desktop.Api().preview("nope.png")
    assert r["ok"] is False and "不存在" in r["error"]
    assert called["n"] == 0   # 文件缺失不开窗


# ---- save_zip:打包多张 ----

def test_save_zip_packs_existing_only(export_dir, tmp_path, monkeypatch):
    dest = str(tmp_path / "out.zip")
    monkeypatch.setattr(desktop, "_window", FakeWindow(dest))
    r = desktop.Api().save_zip(["889635416339_5.png", "missing.png"])
    assert r["ok"] is True and r["count"] == 1
    with zipfile.ZipFile(dest) as z:
        assert z.namelist() == ["889635416339_5.png"]

def test_save_zip_no_valid_files(export_dir, monkeypatch):
    monkeypatch.setattr(desktop, "_window", FakeWindow("/x/out.zip"))
    r = desktop.Api().save_zip(["missing.png"])
    assert r["ok"] is False and "无可导出" in r["error"]

def test_save_zip_cancelled(export_dir, monkeypatch):
    monkeypatch.setattr(desktop, "_window", FakeWindow(None))
    r = desktop.Api().save_zip(["889635416339_5.png"])
    assert r == {"ok": False, "cancelled": True}
