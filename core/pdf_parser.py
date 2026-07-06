# core/pdf_parser.py
import fitz, re
from core import config
from core.fees import extract_fee_rows
from core.classifier import has_extra_fee, has_duty

_AMOUNT_LABELS = [("运费", "freight"), ("折扣", "discount"),
                  ("燃油附加费", "fuel"), ("合计", "total")]

def _is_detail_page(text):
    return any(m in text for m in config.DETAIL_MARKERS)

def _page_invoice_no(words):
    """该页页眉的 invoice number:y<160、x>400 的 9 位数字(区分同一 PDF 内多张 invoice)。
    注意:XXXXX0612 是客户账号(每页固定),不是 invoice 号,不能用。"""
    cands = [w for w in words
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

def _parse_detail_page(page, words, page_no, invoice_no):
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

def _parse_page(page, pno):
    """解析单页:每页只抽一次 words/text 复用,非明细页返回空列表。"""
    text = page.get_text("text")
    if not _is_detail_page(text):
        return []
    words = page.get_text("words")
    return _parse_detail_page(page, words, pno, _page_invoice_no(words))

def parse_pdf(pdf_path, page_range=None, progress_cb=None):
    """解析明细页所有票。page_range=(start,end) 半开(0基),progress_cb(done,total)。
    invoice_no 按每页页眉解析(一份 PDF 可含多张 invoice)。"""
    doc = fitz.open(pdf_path)
    try:
        lo = 0 if page_range is None else page_range[0]
        hi = len(doc) if page_range is None else min(page_range[1], len(doc))
        out = []
        for pno in range(lo, hi):
            out.extend(_parse_page(doc[pno], pno))
            if progress_cb:
                progress_cb(pno - lo + 1, hi - lo)
        return out
    finally:
        doc.close()

def _parse_segment(args):
    """解析 [lo,hi) 页段,返回票列表。供多进程 map 调用,故为模块级、参数可 pickle。"""
    pdf_path, lo, hi = args
    doc = fitz.open(pdf_path)
    try:
        out = []
        for pno in range(lo, hi):
            out.extend(_parse_page(doc[pno], pno))
        return out
    finally:
        doc.close()

def _default_workers():
    """自适应用核:始终留 2 个核给系统/UI,其余用于解析,至少 1。
    随机器核数伸缩,不写死上限:2核→1、4核→2、8核→6、16核→14。"""
    import os
    return max(1, (os.cpu_count() or 2) - 2)

def parse_pdf_parallel(pdf_path, workers=None, seg_pages=200, progress_cb=None):
    """多进程并行解析:按 seg_pages 切段分给进程池。页间独立,绕过 GIL。
    workers=None 时用 _default_workers()(核数一半、封顶4),避免拉爆 CPU。
    progress_cb(done_segs,total_segs) 按段回调。"""
    from concurrent.futures import ProcessPoolExecutor
    doc = fitz.open(pdf_path); total = len(doc); doc.close()
    segs = [(pdf_path, lo, min(lo + seg_pages, total))
            for lo in range(0, total, seg_pages)]
    workers = workers or _default_workers()
    out = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for done, res in enumerate(ex.map(_parse_segment, segs), 1):
            out.extend(res)
            if progress_cb:
                progress_cb(done, len(segs))
    return out

def parse_pdf_stream(pdf_path, batch_pages=200):
    """流式解析:doc 只打开一次,每积满 batch_pages 页 yield 一次
    (done_pages, tickets_batch),供调用方边解析边入库。最后一批含剩余页。"""
    doc = fitz.open(pdf_path)
    try:
        total = len(doc)
        batch = []
        for pno in range(total):
            batch.extend(_parse_page(doc[pno], pno))
            if (pno + 1) % batch_pages == 0:
                yield pno + 1, batch
                batch = []
        yield total, batch
    finally:
        doc.close()
