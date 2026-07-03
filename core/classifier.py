# core/classifier.py
from core import config

def _is_skip(label: str) -> bool:
    return any(s in label for s in config.SKIP_LABELS)

def _is_normal(label: str) -> bool:
    low = label.lower()
    return any(k.lower() in low for k in config.NORMAL_FEES)

def has_extra_fee(fee_rows) -> bool:
    """费用行里出现非白名单科目(排除合计/币种行)→ 有杂费。"""
    for r in fee_rows:
        lab = r["label"].strip()
        if not lab or _is_skip(lab):
            continue
        if not _is_normal(lab):
            return True
    return False

def has_duty(fee_rows) -> bool:
    """关税绑定费用行:费用行科目名含关税关键词才算(地址/说明里的 Customs 不参与)。"""
    for r in fee_rows:
        lab = r["label"]
        if _is_skip(lab):
            continue
        if any(k in lab for k in config.DUTY_KEYWORDS):
            return True
    return False
