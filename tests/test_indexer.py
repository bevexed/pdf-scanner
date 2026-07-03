# tests/test_indexer.py
import os, tempfile
from core import indexer

def _db():
    return os.path.join(tempfile.mkdtemp(), "t.db")

def _ticket(awb, invoice="INV1", page=56):
    return {"awb": awb, "invoice_no": invoice, "source_page_index": page,
            "record_type": "detail", "rect": [0, 160, 595, 285],
            "fee_rows": [], "mask_rects": [{"kind": "sender", "rect": [243, 160, 395, 200]}],
            "has_extra": False, "has_duty": False}

def test_batch_commit_and_lookup():
    db = _db(); indexer.init_db(db)
    bid = indexer.begin_batch(db, "hashA", "a.pdf", 100)
    indexer.insert_tickets(db, bid, [_ticket("889414201705")])
    indexer.commit_batch(db, bid, 1)
    recs = indexer.lookup(db, "889414201705")
    assert len(recs) == 1
    assert recs[0]["invoice_no"] == "INV1"
    assert recs[0]["source_page_index"] == 56

def test_pending_batch_not_visible():
    db = _db(); indexer.init_db(db)
    bid = indexer.begin_batch(db, "hashB", "b.pdf", 10)
    indexer.insert_tickets(db, bid, [_ticket("111111111111")])
    # 未 commit → 查不到
    assert indexer.lookup(db, "111111111111") == []

def test_dedup_by_hash():
    db = _db(); indexer.init_db(db)
    bid = indexer.begin_batch(db, "hashC", "c.pdf", 10)
    indexer.insert_tickets(db, bid, [_ticket("222222222222")])
    indexer.commit_batch(db, bid, 1)
    assert indexer.is_imported(db, "hashC") is True
    assert indexer.is_imported(db, "hashOTHER") is False

def test_begin_batch_clears_previous_pending():
    db = _db(); indexer.init_db(db)
    b1 = indexer.begin_batch(db, "hashD", "d.pdf", 10)
    indexer.insert_tickets(db, b1, [_ticket("333333333333")])
    # 未 commit 就再次 begin 同 hash → 清理旧 pending 半成品
    b2 = indexer.begin_batch(db, "hashD", "d.pdf", 10)
    indexer.insert_tickets(db, b2, [_ticket("333333333333")])
    indexer.commit_batch(db, b2, 1)
    assert len(indexer.lookup(db, "333333333333")) == 1  # 不重复

def test_multi_invoice_candidates():
    db = _db(); indexer.init_db(db)
    for h, inv in [("h1", "INV_A"), ("h2", "INV_B")]:
        bid = indexer.begin_batch(db, h, f"{inv}.pdf", 10)
        indexer.insert_tickets(db, bid, [_ticket("444444444444", invoice=inv)])
        indexer.commit_batch(db, bid, 1)
    recs = indexer.lookup(db, "444444444444")
    assert len(recs) == 2  # 两个账期都返回

def test_lookup_returns_record_id():
    db = _db(); indexer.init_db(db)
    bid = indexer.begin_batch(db, "hashE", "e.pdf", 10)
    indexer.insert_tickets(db, bid, [_ticket("555555555555")])
    indexer.commit_batch(db, bid, 1)
    rec = indexer.lookup(db, "555555555555")[0]
    assert isinstance(rec["id"], int)   # 导出文件名用 id 保证唯一

def test_fail_batch_cleans_up():
    db = _db(); indexer.init_db(db)
    bid = indexer.begin_batch(db, "hashF", "f.pdf", 10)
    indexer.insert_tickets(db, bid, [_ticket("666666666666")])
    indexer.fail_batch(db, bid)          # 模拟中途失败清理
    assert indexer.lookup(db, "666666666666") == []
    assert indexer.is_imported(db, "hashF") is False
