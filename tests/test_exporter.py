# tests/test_exporter.py
import os, pytest
from core.exporter import export_masked, IncompleteMaskError

PDF = "var/CN_XXXXX0612.0002.08051642551452.pdf"
pytestmark = pytest.mark.skipif(not os.path.exists(PDF), reason="训练PDF不在")

def test_export_creates_png(tmp_path):
    from PIL import Image
    rect = [0, 160, 595, 285]
    masks = [{"kind": "sender", "rect": [243, 160, 395, 200]},
             {"kind": "freight", "rect": [535, 209, 565, 218]},
             {"kind": "discount", "rect": [533, 218, 565, 227]},
             {"kind": "fuel", "rect": [539, 226, 565, 235]},
             {"kind": "total", "rect": [535, 239, 565, 248]}]
    out = str(tmp_path / "889414201705.png")
    res = export_masked(PDF, 56, rect, masks, out, required={"sender", "freight", "discount", "fuel", "total"})
    assert os.path.exists(res)
    assert Image.open(res).width > 1000

def test_incomplete_mask_blocks_export(tmp_path):
    rect = [0, 160, 595, 285]
    masks = [{"kind": "sender", "rect": [243, 160, 395, 200]}]  # 缺金额字段
    out = str(tmp_path / "x.png")
    with pytest.raises(IncompleteMaskError):
        export_masked(PDF, 56, rect, masks, out,
                      required={"sender", "freight", "discount", "fuel", "total"})
    assert not os.path.exists(out)  # 不静默导出

def test_solid_mask_fully_opaque(tmp_path):
    # 默认 solid:遮盖区域应是纯色(方差极低)
    from PIL import Image
    import statistics
    rect = [0, 160, 595, 285]
    masks = [{"kind": "sender", "rect": [243, 160, 395, 200]}]
    out = str(tmp_path / "s.png")
    export_masked(PDF, 56, rect, masks, out, required={"sender"})
    img = Image.open(out).convert("L")
    z = 3
    box = (int(243*z), int(2*z), int(300*z), int(38*z))  # 遮盖区一角
    px = list(img.crop(box).getdata())
    assert statistics.pstdev(px) < 5  # 近乎纯色
