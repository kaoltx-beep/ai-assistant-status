"""Optional screenshot downscaling.

A 1080x2400 PNG is ~1-2 MB; over mobile data that is slow and expensive in
tokens. If Pillow is available (Termux: `pkg install python-pillow`) we shrink
the image before sending it. If not, we send it as-is — nothing breaks.
"""

from __future__ import annotations

import io


def downscale_png(png: bytes, target_width: int) -> tuple[bytes, float]:
    """Return (png_bytes, scale) where scale = sent_width / real_width."""
    if target_width <= 0:
        return png, 1.0

    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return png, 1.0

    try:
        with Image.open(io.BytesIO(png)) as img:
            if img.width <= target_width:
                return png, 1.0
            ratio = target_width / float(img.width)
            new_size = (target_width, max(1, int(img.height * ratio)))
            resized = img.convert("RGB").resize(new_size, Image.LANCZOS)
            buffer = io.BytesIO()
            resized.save(buffer, format="PNG", optimize=True)
            return buffer.getvalue(), ratio
    except Exception:  # noqa: BLE001 - a broken image must not kill the run
        return png, 1.0
