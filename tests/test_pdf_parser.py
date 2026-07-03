# tests/test_pdf_parser.py
import os, pytest
from core.pdf_parser import parse_pdf

PDF = "var/CN_XXXXX0612.0002.08051642551452.pdf"
pytestmark = pytest.mark.skipif(not os.path.exists(PDF), reason="训练PDF不在")

def _find(ts, awb):
    return next((t for t in ts if t["awb"] == awb), None)

@pytest.fixture(scope="module")
def p56():
    return parse_pdf(PDF, page_range=(56, 57))

def test_summary_page_yields_zero_tickets():
    # 0 基前两页均为摘要页(无 BILLING DETAIL),必须跳过
    assert parse_pdf(PDF, page_range=(0, 1)) == []
    assert parse_pdf(PDF, page_range=(1, 2)) == []

def test_finds_awbs_on_detail_page(p56):
    awbs = {t["awb"] for t in p56}
    assert "889414201705" in awbs and "889635416339" in awbs

def test_normal_ticket_no_extra(p56):
    assert _find(p56, "889414201705")["has_extra"] is False

def test_extra_fee_ticket(p56):
    assert _find(p56, "889635416339")["has_extra"] is True

def test_ticket_rect_reasonable(p56):
    x0, y0, x1, y1 = _find(p56, "889414201705")["rect"]
    assert x1 - x0 > 400 and 100 < y1 - y0 < 140

def test_mask_rects_present(p56):
    t = _find(p56, "889414201705")
    kinds = {m["kind"] for m in t["mask_rects"]}
    assert "sender" in kinds
    assert {"freight", "discount", "fuel", "total"} <= kinds

def test_mixed_page_per_ticket_classification():
    ts = parse_pdf(PDF, page_range=(189, 190))
    by = {t["awb"]: t["has_extra"] for t in ts}
    assert by["889960390297"] is True and by["889960402673"] is True
    assert by["889960401200"] is False and by["889960464719"] is False
    assert by["889960474640"] is False  # Demand Surcharge 常规

def test_vat_in_address_not_extra_or_duty():
    ts = parse_pdf(PDF, page_range=(191, 192))
    t = _find(ts, "889960603046")
    assert t is not None
    assert t["has_extra"] is False and t["has_duty"] is False

def test_invoice_no_from_page_header(p56):
    # 页眉 invoice 号,非客户账号 XXXXX0612
    t = _find(p56, "889414201705")
    assert t["invoice_no"] == "953984390"

def test_invoice_no_differs_across_invoices():
    # 同一 PDF 后段是另一张 invoice(p725 起为 954005119 的明细页),不能都标成第一张
    ts = parse_pdf(PDF, page_range=(725, 726))
    assert ts, "p725 应为明细页且有票"
    assert all(t["invoice_no"] == "954005119" for t in ts)
