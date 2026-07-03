# core/pdf_parser.py
import fitz, re
from core import config
from core.fees import extract_fee_rows
from core.classifier import has_extra_fee, has_duty

_AMOUNT_LABELS = [("运费", "freight"), ("折扣", "discount"),
                  ("燃油附加费", "fuel"), ("合计", "total")]

def _is_detail_page(page):
    t = page.get_text("text")
    return any(m in t for m in config.DETAIL_MARKERS)

def _page_invoice_no(page):
    """该页页眉的 invoice number:y<160、x>400 的 9 位数字(区分同一 PDF 内多张 invoice)。
    注意:XXXXX0612 是客户账号(每页固定),不是 invoice 号,不能用。"""
    cands = [w for w in page.get_text("words")
             if w[1] < 160 and w[0] > 400 and re.match(r"^\d{9}$", w[4])]
    return cands[0][4] if cands else ""

def _amount_rect_for(words, label, y_lo, y_hi):
    """在 [y_lo,y_hi) 内找费用列标签 label 所在行、x≥AMOUNT_MIN_X 的 ￥ 坐标。"""
    lab = next((w for w in words if w[4] == label
                and config.FEE_LABEL_X_RANGE[0] <= w[0] < config.FEE_LABEL_X_RANGE[1]
                and y_lo <= w[1] < y_hi), None)
    if not lab:
        return None
    amt = next((w for w in words if abs(w[1] - lab[1]) <= config.ROW_Y_TOL
                and w[0] >= config.AMOUNT_MIN_X and "￥" in w[4]), None)
    return [amt[0], amt[1], amt[2], amt[3]] if amt else None

def _sender_rect(words, y_lo, y_hi):
    xs0, xs1 = config.SENDER_X_RANGE
    sel = [w for w in words if y_lo <= w[1] < y_hi and w[0] >= xs0 and w[2] <= xs1 + 5]
    if not sel:
        return None
    return [min(w[0] for w in sel), min(w[1] for w in sel),
            max(w[2] for w in sel), max(w[3] for w in sel)]

def _parse_detail_page(page, page_no, invoice_no):
    words = page.get_text("words")
    anchors = []
    for w in words:
        if w[4] == "AWB":
            num = next((v for v in words if abs(v[1] - w[1]) <= config.ROW_Y_TOL
                        and config.AWB_RE.match(v[4])), None)
            if num:
                anchors.append((w[1], num[4]))
    anchors.sort(key=lambda t: t[0])

    out = []
    for i, (y_top, awb) in enumerate(anchors):
        y_bottom = anchors[i + 1][0] if i + 1 < len(anchors) else page.rect.y1
        rect = fitz.Rect(page.rect.x0, y_top - config.TICKET_TOP_PAD,
                         page.rect.x1, y_bottom - config.TICKET_BOTTOM_PAD)
        fee_rows = extract_fee_rows(page, rect.y0, rect.y1)

        mask_rects = []
        freight_y = next((w[1] for w in words
                          if w[4] == "运费" and rect.y0 <= w[1] < rect.y1), rect.y1)
        s = _sender_rect(words, rect.y0, freight_y)
        if s:
            mask_rects.append({"kind": "sender", "rect": s})
        for label, kind in _AMOUNT_LABELS:
            ar = _amount_rect_for(words, label, rect.y0, rect.y1)
            if ar:
                mask_rects.append({"kind": kind, "rect": ar})

        out.append({
            "awb": awb, "invoice_no": invoice_no,
            "source_page_index": page_no, "record_type": "detail",
            "rect": [rect.x0, rect.y0, rect.x1, rect.y1],
            "fee_rows": fee_rows, "mask_rects": mask_rects,
            "has_extra": has_extra_fee(fee_rows),
            "has_duty": has_duty(fee_rows),
        })
    return out

def parse_pdf(pdf_path, page_range=None, progress_cb=None):
    """解析明细页所有票。page_range=(start,end) 半开(0基),progress_cb(done,total)。
    invoice_no 按每页页眉解析(一份 PDF 可含多张 invoice)。"""
    doc = fitz.open(pdf_path)
    lo = 0 if page_range is None else page_range[0]
    hi = len(doc) if page_range is None else min(page_range[1], len(doc))
    out = []
    for pno in range(lo, hi):
        page = doc[pno]
        if _is_detail_page(page):
            out.extend(_parse_detail_page(page, pno, _page_invoice_no(page)))
        if progress_cb:
            progress_cb(pno - lo + 1, hi - lo)
    doc.close()
    return out
