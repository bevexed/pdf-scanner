# core/fees.py
from core import config

def extract_fee_rows(page, y0, y1):
    """从页面 [y0,y1) 区域,用 words 坐标提取费用行。
    返回 [{"label": 科目名, "amount_text": "￥..", "amount_rect": [x0,y0,x1,y1]}]。
    识别法:每个 x≥AMOUNT_MIN_X 且含￥的 word 是一行金额,同 y 的费用列标签词拼成 label。"""
    words = [w for w in page.get_text("words") if y0 <= w[1] < y1]
    lx0, lx1 = config.FEE_LABEL_X_RANGE
    rows = []
    for a in words:
        if a[0] < config.AMOUNT_MIN_X or "￥" not in a[4]:
            continue
        labs = [w for w in words
                if abs(w[1] - a[1]) <= config.ROW_Y_TOL and lx0 <= w[0] < lx1]
        labs.sort(key=lambda w: w[0])
        rows.append({
            "label": " ".join(w[4] for w in labs),
            "amount_text": a[4],
            "amount_rect": [a[0], a[1], a[2], a[3]],
        })
    return rows
