# core/exporter.py
import fitz, os
from PIL import Image, ImageFilter, ImageDraw
from core import config

class IncompleteMaskError(Exception):
    """必打码字段缺失,拒绝导出。"""

def export_masked(pdf_path, page_no, rect, mask_rects, out_path, required=None):
    """渲染区域→遮盖→存 PNG。required: 必须齐全的 kind 集合,缺则抛 IncompleteMaskError。"""
    if required:
        have = {m["kind"] for m in mask_rects}
        missing = set(required) - have
        if missing:
            raise IncompleteMaskError(f"打码不完整,缺字段: {sorted(missing)}")

    z = config.RENDER_ZOOM
    doc = fitz.open(pdf_path)
    page = doc[page_no]
    pix = page.get_pixmap(matrix=fitz.Matrix(z, z), clip=fitz.Rect(*rect))
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    draw = ImageDraw.Draw(img)
    for m in mask_rects:
        r = m["rect"]
        box = (max(0, int((r[0]-rect[0])*z)), max(0, int((r[1]-rect[1])*z)),
               min(img.width, int((r[2]-rect[0])*z)), min(img.height, int((r[3]-rect[1])*z)))
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        if config.MASK_MODE == "blur":
            img.paste(img.crop(box).filter(ImageFilter.GaussianBlur(config.BLUR_RADIUS)), box)
        else:  # solid 默认:实心遮盖,颜色可配(默认与账单底色同色)
            draw.rectangle(box, fill=tuple(config.MASK_COLOR))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path)
    doc.close()
    return out_path
