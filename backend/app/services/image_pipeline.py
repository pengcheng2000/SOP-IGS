from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover - optional during lightweight tooling
    pass


class ImagePipelineError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ProcessedImage:
    sha256: str
    detected_format: str
    mime_type: str
    original_width: int
    original_height: int
    processed_width: int
    processed_height: int
    output_extension: str
    data: bytes


def _to_srgb(image: Image.Image) -> Image.Image:
    profile = image.info.get("icc_profile")
    if not profile:
        return image
    try:
        source = ImageCms.ImageCmsProfile(BytesIO(profile))
        target = ImageCms.createProfile("sRGB")
        return ImageCms.profileToProfile(image, source, target, outputMode=image.mode)
    except (OSError, ValueError):
        return image


def process_image(
    source: bytes,
    *,
    max_bytes: int,
    max_pixels: int,
    max_long_edge: int = 2400,
    jpeg_quality: int = 88,
) -> ProcessedImage:
    if not source:
        raise ImagePipelineError("IMAGE_DECODE_FAILED", "图片为空")
    if len(source) > max_bytes:
        raise ImagePipelineError("PHOTO_LIMIT_EXCEEDED", "单张图片超过大小限制")
    digest = hashlib.sha256(source).hexdigest()
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        with Image.open(BytesIO(source)) as opened:
            detected = (opened.format or "").upper()
            if detected not in {"JPEG", "PNG", "HEIF", "HEIC"}:
                raise ImagePipelineError("IMAGE_DECODE_FAILED", f"不支持的图片格式：{detected or 'unknown'}")
            frame = opened.copy()
    except Image.DecompressionBombError as exc:
        raise ImagePipelineError("IMAGE_DECODE_FAILED", "图片像素数量超过安全限制") from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImagePipelineError("IMAGE_DECODE_FAILED", "无法解码图片") from exc

    original_width, original_height = frame.size
    if original_width * original_height > max_pixels:
        raise ImagePipelineError("IMAGE_DECODE_FAILED", "图片像素数量超过安全限制")
    frame = ImageOps.exif_transpose(frame)
    frame = _to_srgb(frame)
    if max(frame.size) > max_long_edge:
        scale = max_long_edge / max(frame.size)
        frame = frame.resize(
            (max(1, round(frame.width * scale)), max(1, round(frame.height * scale))),
            Image.Resampling.LANCZOS,
        )

    has_alpha = frame.mode in {"RGBA", "LA"} or "transparency" in frame.info
    output = BytesIO()
    if has_alpha:
        if frame.mode != "RGBA":
            frame = frame.convert("RGBA")
        frame.save(output, format="PNG", optimize=True)
        extension, mime = ".png", "image/png"
    else:
        if frame.mode != "RGB":
            frame = frame.convert("RGB")
        frame.save(output, format="JPEG", quality=jpeg_quality, optimize=True, progressive=False)
        extension, mime = ".jpg", "image/jpeg"

    data = output.getvalue()
    return ProcessedImage(
        sha256=digest,
        detected_format=detected,
        mime_type=mime,
        original_width=original_width,
        original_height=original_height,
        processed_width=frame.width,
        processed_height=frame.height,
        output_extension=extension,
        data=data,
    )


def image_dimensions(path: str | Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size

