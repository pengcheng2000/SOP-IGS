from io import BytesIO

import pytest
from app.services.image_pipeline import ImagePipelineError, process_image
from PIL import Image
from pillow_heif import from_pillow


def encode(image: Image.Image, format_name: str, **kwargs) -> bytes:
    output = BytesIO()
    image.save(output, format=format_name, **kwargs)
    return output.getvalue()


def test_applies_exif_rotation_and_removes_metadata():
    image = Image.new("RGB", (80, 40), "red")
    exif = Image.Exif()
    exif[274] = 6
    result = process_image(
        encode(image, "JPEG", exif=exif), max_bytes=1024 * 1024, max_pixels=1_000_000
    )
    assert (result.processed_width, result.processed_height) == (40, 80)
    with Image.open(BytesIO(result.data)) as decoded:
        assert decoded.getexif().get(274) is None


def test_preserves_alpha_as_png():
    image = Image.new("RGBA", (40, 40), (20, 80, 120, 100))
    result = process_image(
        encode(image, "PNG"), max_bytes=1024 * 1024, max_pixels=1_000_000
    )
    assert result.output_extension == ".png"
    assert result.mime_type == "image/png"


def test_accepts_heic_and_normalizes_to_jpeg():
    output = BytesIO()
    from_pillow(Image.new("RGB", (64, 48), "green")).save(output, quality=80)
    result = process_image(output.getvalue(), max_bytes=1024 * 1024, max_pixels=1_000_000)
    assert result.detected_format in {"HEIF", "HEIC"}
    assert result.output_extension == ".jpg"


def test_rejects_invalid_payload():
    with pytest.raises(ImagePipelineError) as error:
        process_image(b"not-an-image", max_bytes=1024, max_pixels=1_000_000)
    assert error.value.code == "IMAGE_DECODE_FAILED"

