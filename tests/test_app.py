# tests/test_app.py
import os, tempfile
import core.config as _cfg
_cfg.DATA_DIR = tempfile.mkdtemp()
_cfg.DB_PATH = os.path.join(_cfg.DATA_DIR, "t.db")
_cfg.PDF_DIR = os.path.join(_cfg.DATA_DIR, "pdfs")
_cfg.EXPORT_DIR = os.path.join(_cfg.DATA_DIR, "exports")
os.makedirs(_cfg.PDF_DIR, exist_ok=True); os.makedirs(_cfg.EXPORT_DIR, exist_ok=True)
import app as appmod
appmod._ensure_dirs()

def client():
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()

def test_index_ok():
    assert client().get("/").status_code == 200

def test_progress_default():
    assert "state" in client().get("/progress").get_json()

def test_query_unknown(monkeypatch):
    monkeypatch.setattr(appmod.indexer, "lookup", lambda db, awb: [])
    r = client().post("/query", json={"awbs": ["000000000000"], "mode": "fee"})
    assert r.get_json()[0]["status"] == "未找到"

def test_query_returns_candidates(monkeypatch):
    recs = [
        {"id": 1, "awb": "889635416339", "invoice_no": "INV_A", "source_page_index": 56,
         "record_type": "detail", "pdf_hash": "h", "rect": [0,160,595,285],
         "mask_rects": [], "has_extra": True, "has_duty": False},
        {"id": 2, "awb": "889635416339", "invoice_no": "INV_B", "source_page_index": 60,
         "record_type": "detail", "pdf_hash": "h2", "rect": [0,160,595,285],
         "mask_rects": [], "has_extra": True, "has_duty": False},
    ]
    monkeypatch.setattr(appmod.indexer, "lookup", lambda db, awb: recs)
    monkeypatch.setattr(appmod, "_pdf_path_for", lambda h: "var/x.pdf")
    monkeypatch.setattr(appmod.exporter, "export_masked",
                        lambda *a, **k: None)  # 不抛异常即视为导出成功;out 名由 query 内部构造
    r = client().post("/query", json={"awbs": ["889635416339"], "mode": "fee"})
    data = r.get_json()
    # 两个账期候选都返回,带来源账单号,图片名用 id 区分
    assert len(data) == 2
    assert {d["invoice_no"] for d in data} == {"INV_A", "INV_B"}
    assert data[0]["status"] == "有杂费"
    assert {d["image"] for d in data} == {"/exports/889635416339_1.png", "/exports/889635416339_2.png"}

def test_query_incomplete_mask(monkeypatch):
    rec = [{"id": 1, "awb": "889635416339", "invoice_no": "INV_A", "source_page_index": 56,
            "record_type": "detail", "pdf_hash": "h", "rect": [0,160,595,285],
            "mask_rects": [], "has_extra": True, "has_duty": False}]
    monkeypatch.setattr(appmod.indexer, "lookup", lambda db, awb: rec)
    monkeypatch.setattr(appmod, "_pdf_path_for", lambda h: "var/x.pdf")
    def _raise(*a, **k):
        from core.exporter import IncompleteMaskError
        raise IncompleteMaskError("缺字段")
    monkeypatch.setattr(appmod.exporter, "export_masked", _raise)
    r = client().post("/query", json={"awbs": ["889635416339"], "mode": "fee"})
    assert r.get_json()[0]["status"] == "打码不完整"

def test_query_missing_source_pdf(monkeypatch):
    rec = [{"id": 1, "awb": "889635416339", "invoice_no": "INV_A", "source_page_index": 56,
            "record_type": "detail", "pdf_hash": "gone", "rect": [0,160,595,285],
            "mask_rects": [], "has_extra": True, "has_duty": False}]
    monkeypatch.setattr(appmod.indexer, "lookup", lambda db, awb: rec)
    monkeypatch.setattr(appmod, "_pdf_path_for", lambda h: None)  # 源 PDF 找不到
    r = client().post("/query", json={"awbs": ["889635416339"], "mode": "fee"})
    d = r.get_json()[0]
    assert d["status"] == "源PDF缺失"  # 不是 500
