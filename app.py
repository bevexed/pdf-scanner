# app.py
import os, threading, zipfile, io
from flask import (Flask, request, jsonify, render_template,
                   send_from_directory, send_file)
from core import config, indexer, exporter
from core.pdf_parser import parse_pdf
import fitz

app = Flask(__name__, template_folder=os.path.join(config.WEB_DIR, "templates"),
            static_folder=os.path.join(config.WEB_DIR, "static"))

_progress = {"state": "idle", "done": 0, "total": 0, "tickets": 0, "message": ""}
_REQUIRED_MASK = {"sender", "freight", "discount", "fuel", "total"}

def is_busy():
    """导入进行中(供桌面外壳判断是否可安全退出)。"""
    return _progress["state"] == "parsing"

def _ensure_dirs():
    for d in (config.DATA_DIR, config.PDF_DIR, config.EXPORT_DIR):
        os.makedirs(d, exist_ok=True)
    indexer.init_db(config.DB_PATH)

def _pdf_path_for(pdf_hash):
    """按 hash 找已保存的 PDF(文件名以 hash 命名,避免同名覆盖)。"""
    for f in os.listdir(config.PDF_DIR):
        if f.startswith(pdf_hash):
            return os.path.join(config.PDF_DIR, f)
    return None

@app.route("/")
def index():
    return render_template("index.html", total=indexer.total_tickets(config.DB_PATH))

@app.route("/progress")
def progress():
    return jsonify(_progress)

def _do_import(save_path, pdf_hash):
    global _progress
    try:
        doc = fitz.open(save_path); total = len(doc); doc.close()
        if indexer.is_imported(config.DB_PATH, pdf_hash):
            _progress = {"state": "done", "done": total, "total": total,
                         "tickets": indexer.total_tickets(config.DB_PATH),
                         "message": "该文件已导入,跳过"}
            return
        _progress = {"state": "parsing", "done": 0, "total": total, "tickets": 0, "message": ""}
        bid = indexer.begin_batch(config.DB_PATH, pdf_hash, os.path.basename(save_path), total)
        STEP = 200; count = 0
        try:
            for lo in range(0, total, STEP):
                tickets = parse_pdf(save_path, (lo, min(lo + STEP, total)))
                indexer.insert_tickets(config.DB_PATH, bid, tickets)
                count += len(tickets)
                _progress["done"] = min(lo + STEP, total)
            indexer.commit_batch(config.DB_PATH, bid, count)   # 整批成功才可见
        except Exception:
            indexer.fail_batch(config.DB_PATH, bid)            # 清理半成品记录
            raise
        _progress["state"] = "done"
        _progress["tickets"] = indexer.total_tickets(config.DB_PATH)
    except Exception as e:
        _progress["state"] = "error"; _progress["message"] = str(e)

@app.route("/import", methods=["POST"])
def import_pdf():
    f = request.files["file"]
    data = f.read()
    import hashlib
    pdf_hash = hashlib.sha1(data).hexdigest()
    save_path = os.path.join(config.PDF_DIR, f"{pdf_hash}_{os.path.basename(f.filename)}")
    with open(save_path, "wb") as out:
        out.write(data)
    threading.Thread(target=_do_import, args=(save_path, pdf_hash), daemon=True).start()
    return jsonify({"ok": True})

@app.route("/query", methods=["POST"])
def query():
    body = request.get_json()
    awbs = [a.strip() for a in body["awbs"] if a.strip()]
    mode = body.get("mode", "fee")
    results = []
    for awb in awbs:
        recs = indexer.lookup(config.DB_PATH, awb)
        if not recs:
            results.append({"awb": awb, "status": "未找到"}); continue
        for rec in recs:   # 候选列表:每条一行
            hit = rec["has_extra"] if mode == "fee" else rec["has_duty"]
            base = {"awb": awb, "invoice_no": rec["invoice_no"],
                    "page": rec["source_page_index"]}
            if not hit:
                base["status"] = "无杂费" if mode == "fee" else "无关税"
                results.append(base); continue
            masks = rec["mask_rects"]
            required = _REQUIRED_MASK if mode == "fee" else {"sender"}
            if mode == "duty":
                masks = [m for m in masks if m["kind"] == "sender"]
            pdf_path = _pdf_path_for(rec["pdf_hash"])
            if not pdf_path:
                base["status"] = "源PDF缺失"; base["message"] = "请重新导入该账单"
                results.append(base); continue
            # 文件名用记录 id 保证唯一(不同 invoice/页的同一 AWB 不互相覆盖)
            out = os.path.join(config.EXPORT_DIR, f"{awb}_{rec['id']}.png")
            try:
                exporter.export_masked(pdf_path, rec["source_page_index"], rec["rect"],
                                       masks, out, required=required)
                base["status"] = "有杂费" if mode == "fee" else "有关税"
                base["image"] = f"/exports/{os.path.basename(out)}"
            except exporter.IncompleteMaskError as e:
                base["status"] = "打码不完整"; base["message"] = str(e)
            results.append(base)
    return jsonify(results)

@app.route("/exports/<path:name>")
def exports(name):
    return send_from_directory(config.EXPORT_DIR, name)

@app.route("/export_zip", methods=["POST"])
def export_zip():
    names = request.get_json()["files"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in names:
            p = os.path.join(config.EXPORT_DIR, name)
            if os.path.exists(p):
                z.write(p, name)
    buf.seek(0)
    return send_file(buf, mimetype="application/zip",
                     as_attachment=True, download_name="exports.zip")

if __name__ == "__main__":
    _ensure_dirs()
    app.run(host="127.0.0.1", port=5000)
