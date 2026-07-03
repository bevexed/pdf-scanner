# tests/test_classifier.py
from core.classifier import has_extra_fee, has_duty

def R(label, amt="￥1.00"):
    return {"label": label, "amount_text": amt, "amount_rect": [530, 0, 564, 8]}

NORMAL = [R("运费 Freight"), R("折扣 Discount"), R("燃油附加费 Fuel Surcharge"),
          R("合计 Total CNY")]
EXTRA  = [R("运费 Freight"), R("超范围派送费 A Out of Delivery Area Tier A"),
          R("燃油附加费 Fuel Surcharge"), R("合计 Total CNY")]
DEMAND = [R("运费 Freight"), R("Demand Surcharge"), R("合计 Total CNY")]
DUTY   = [R("运费 Freight"), R("多米尼加海关用户费 Dominican Customs User Fee"),
          R("合计 Total CNY")]

def test_normal_no_extra():
    assert has_extra_fee(NORMAL) is False

def test_extra_detected():
    assert has_extra_fee(EXTRA) is True

def test_total_cny_row_not_extra():
    # 合计行(含 CNY)不能误判为杂费
    assert has_extra_fee([R("合计 Total CNY")]) is False

def test_demand_surcharge_normal():
    assert has_extra_fee(DEMAND) is False

def test_duty_bound_to_fee_row():
    assert has_duty(DUTY) is True

def test_no_duty_in_normal():
    assert has_duty(NORMAL) is False
