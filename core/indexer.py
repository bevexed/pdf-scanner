# core/indexer.py
import sqlite3, json, datetime, hashlib

_SCHEMA = """
CREATE TABLE IF NOT EXISTS billing_index (
  id INTEGER PRIMARY KEY,
  awb TEXT, pdf_hash TEXT, invoice_no TEXT,
  source_page_index INTEGER, record_type TEXT,
  rect TEXT, fee_rows TEXT, mask_rects TEXT,
  bill_type TEXT, has_extra INTEGER, has_duty INTEGER,
  import_batch_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_awb ON billing_index(awb);
CREATE TABLE IF NOT EXISTS import_batches (
  id INTEGER PRIMARY KEY,
  pdf_hash TEXT, pdf_file TEXT, page_count INTEGER,
  imported_at TEXT, ticket_count INTEGER, status TEXT
);
CREATE INDEX IF NOT EXISTS idx_batch_hash ON import_batches(pdf_hash);
"""

def _conn(db):
    c = sqlite3.connect(db); c.row_factory = sqlite3.Row; return c

def init_db(db):
    with _conn(db) as c:
        c.executescript(_SCHEMA)

def hash_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def is_imported(db, pdf_hash):
    with _conn(db) as c:
        r = c.execute("SELECT 1 FROM import_batches WHERE pdf_hash=? AND status='committed'",
                      (pdf_hash,)).fetchone()
    return r is not None

def begin_batch(db, pdf_hash, pdf_file, page_count):
    """开新批次(pending)。先清理同 hash 的旧 pending 半成品。"""
    with _conn(db) as c:
        old = [r[0] for r in c.execute(
            "SELECT id FROM import_batches WHERE pdf_hash=? AND status='pending'", (pdf_hash,))]
        for bid in old:
            c.execute("DELETE FROM billing_index WHERE import_batch_id=?", (bid,))
            c.execute("DELETE FROM import_batches WHERE id=?", (bid,))
        cur = c.execute(
            "INSERT INTO import_batches (pdf_hash,pdf_file,page_count,imported_at,ticket_count,status)"
            " VALUES (?,?,?,?,0,'pending')",
            (pdf_hash, pdf_file, page_count, datetime.datetime.now().isoformat()))
        return cur.lastrowid

def insert_tickets(db, batch_id, tickets):
    # bill_type 不写死:当前 PDF 均为运费账单,类型由查询模式(fee/duty)决定,此处留 NULL
    with _conn(db) as c:
        c.executemany(
            """INSERT INTO billing_index
               (awb,pdf_hash,invoice_no,source_page_index,record_type,rect,fee_rows,
                mask_rects,bill_type,has_extra,has_duty,import_batch_id)
               VALUES (?,(SELECT pdf_hash FROM import_batches WHERE id=?),?,?,?,?,?,?,NULL,?,?,?)""",
            [(t["awb"], batch_id, t["invoice_no"], t["source_page_index"], t["record_type"],
              json.dumps(t["rect"]), json.dumps(t["fee_rows"], ensure_ascii=False),
              json.dumps(t["mask_rects"]),
              int(t["has_extra"]), int(t["has_duty"]), batch_id) for t in tickets])

def commit_batch(db, batch_id, ticket_count):
    with _conn(db) as c:
        c.execute("UPDATE import_batches SET status='committed', ticket_count=? WHERE id=?",
                  (ticket_count, batch_id))

def fail_batch(db, batch_id):
    """导入失败:删除该批次已插入的半成品记录并标记 failed(真正清理,不留垃圾)。"""
    with _conn(db) as c:
        c.execute("DELETE FROM billing_index WHERE import_batch_id=?", (batch_id,))
        c.execute("UPDATE import_batches SET status='failed' WHERE id=?", (batch_id,))

def lookup(db, awb):
    """返回该 AWB 在已提交批次里的所有记录(候选列表),按明细优先+页码排序。含记录 id。"""
    with _conn(db) as c:
        rows = c.execute(
            """SELECT b.* FROM billing_index b
               JOIN import_batches ib ON b.import_batch_id=ib.id
               WHERE b.awb=? AND ib.status='committed'
               ORDER BY (b.record_type='detail') DESC, ib.imported_at DESC,
                        b.source_page_index ASC""", (awb,)).fetchall()
    out = []
    for r in rows:
        out.append({"id": r["id"], "awb": r["awb"], "pdf_hash": r["pdf_hash"],
                    "invoice_no": r["invoice_no"],
                    "source_page_index": r["source_page_index"], "record_type": r["record_type"],
                    "rect": json.loads(r["rect"]), "mask_rects": json.loads(r["mask_rects"]),
                    "has_extra": bool(r["has_extra"]), "has_duty": bool(r["has_duty"])})
    return out

def total_tickets(db):
    with _conn(db) as c:
        return c.execute(
            """SELECT COUNT(*) FROM billing_index b JOIN import_batches ib
               ON b.import_batch_id=ib.id WHERE ib.status='committed'""").fetchone()[0]
