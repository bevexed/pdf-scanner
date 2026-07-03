# tests/test_fees.py
import os, pytest, fitz
from core.fees import extract_fee_rows

PDF = "var/CN_XXXXX0612.0002.08051642551452.pdf"
pytestmark = pytest.mark.skipif(not os.path.exists(PDF), reason="训练PDF不在")

def _rows(page_no, y0, y1):
    doc = fitz.open(PDF); page = doc[page_no]
    r = extract_fee_rows(page, y0, y1); doc.close(); return r

def test_normal_ticket_fee_rows():
    # p56 第一票 889414201705 约 y 160-285
    rows = _rows(56, 160, 285)
    labels = [r["label"] for r in rows]
    assert any("运费" in l for l in labels)
    assert any("折扣" in l for l in labels)
    assert any("燃油" in l for l in labels)
    # 每个费用行都有金额矩形
    for r in rows:
        assert len(r["amount_rect"]) == 4
        assert "￥" in r["amount_text"]

def test_extra_fee_row_captured():
    # 有超范围派送费的票 889635416339 约 y 672-800
    rows = _rows(56, 672, 800)
    assert any("超范围派送费" in r["label"] for r in rows)
