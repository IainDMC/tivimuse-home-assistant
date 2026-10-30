"""Contain EPG logos inside square artwork tiles instead of allowing cover cropping."""

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError


def fit_logo(data: bytes) -> tuple[bytes, str] | None:
    """Return square PNG artwork with the complete logo and a small safe inset."""
    try:
        with Image.open(BytesIO(data)) as source:
            logo = ImageOps.exif_transpose(source).convert("RGBA")
            fitted = ImageOps.contain(logo, (480, 480), Image.Resampling.LANCZOS)
            tile = Image.new("RGBA", (512, 512))
            tile.alpha_composite(fitted, ((512 - fitted.width) // 2, (512 - fitted.height) // 2))
            output = BytesIO()
            tile.save(output, format="PNG")
            return output.getvalue(), "image/png"
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        return None
