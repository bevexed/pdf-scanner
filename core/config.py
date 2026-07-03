# core/config.py
import os, re, sys

# ---- 科目字典(可编辑扩充)----
NORMAL_FEES = [
    "运费", "Freight", "折扣", "Discount",
    "燃油附加费", "Fuel Surcharge", "Demand Surcharge",
]
DUTY_KEYWORDS = ["关税", "Duty", "Customs", "海关"]

# 费用行判定里需排除的非科目标记(合计行/币种)
SKIP_LABELS = ("合计", "Total", "CNY", "USD", "EUR", "汇率", "Conversion")

AMOUNT_RE = re.compile(r"￥-?[\d,]+\.?\d*")
AWB_RE = re.compile(r"^\d{12}$")

# ---- 布局参数(真实 PDF 实测)----
SENDER_X_RANGE = (243, 395)     # 寄件人列
FEE_LABEL_X_RANGE = (295, 430)  # 费用科目标签列
AMOUNT_MIN_X = 530              # 金额￥最小 x
ROW_Y_TOL = 3.0                 # 同行 y 容差
TICKET_TOP_PAD = 8
TICKET_BOTTOM_PAD = 4
RENDER_ZOOM = 3
MASK_MODE = "solid"            # "solid" 实心黑遮盖(默认,隐私优先) / "blur" 高斯模糊
BLUR_RADIUS = 12

# 明细页标记
DETAIL_MARKERS = ("账单明细", "BILLING DETAIL")
SUMMARY_MARKERS = ("账单摘要", "Invoice Summary")

# ---- 路径:PyInstaller --onefile 适配(资源与运行数据分离)----
_FROZEN = getattr(sys, "frozen", False)
# 资源(web 模板/静态):冻结时在解压临时目录 _MEIPASS
RESOURCE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 运行数据:冻结时在 exe 真实所在目录旁(否则写临时目录、退出即丢)
_RUN_DIR = (os.path.dirname(sys.executable) if _FROZEN
            else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(_RUN_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "billing_index.db")
PDF_DIR = os.path.join(DATA_DIR, "pdfs")
EXPORT_DIR = os.path.join(DATA_DIR, "exports")
WEB_DIR = os.path.join(RESOURCE_DIR, "web")
