# tests/test_config.py
import os, importlib
from core import config

def test_normal_fees():
    for k in ("运费", "Fuel Surcharge", "Demand Surcharge"):
        assert k in config.NORMAL_FEES

def test_duty_keywords():
    assert "Customs" in config.DUTY_KEYWORDS and "关税" in config.DUTY_KEYWORDS

def test_layout_params():
    assert config.SENDER_X_RANGE == (243, 395)
    assert config.AMOUNT_MIN_X == 530
    assert config.RENDER_ZOOM == 3

def test_mask_mode_default_solid():
    # 隐私优先:默认实心遮盖,不是模糊
    assert config.MASK_MODE == "solid"

def test_data_dir_beside_executable_not_meipass():
    # 未冻结时数据目录在项目根,且与资源目录概念区分。
    # 重新 import 取模块默认值:test_app 会在其 import 期永久改写 config.DATA_DIR
    # 为临时目录(那是必要的,须在 `import app` 前生效),故此处以纯净默认值断言,
    # 避免测试执行顺序耦合。
    fresh = importlib.reload(config)
    assert fresh.DATA_DIR.endswith("data")
    assert os.path.isabs(fresh.DATA_DIR)
    assert os.path.isabs(fresh.RESOURCE_DIR)
