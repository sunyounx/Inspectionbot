from __future__ import annotations

import io

from PIL import Image


def resize_thumbnail(data: bytes, max_size: int = 400) -> tuple[bytes, str]:
    """이미지를 max_size px 이내로 리사이즈, JPEG로 변환."""
    img = Image.open(io.BytesIO(data))
    img.thumbnail((max_size, max_size))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue(), "image/jpeg"
