from __future__ import annotations

import io
import urllib.request
from collections import Counter
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "frontend" / "public" / "brand"
LOGO_URL = "https://www.chintglobal.com/content/dam/chintsite/common/system/logo.png"
FAVICON_URL = "https://www.chintglobal.com/content/dam/chintsite/common/system/favicon.ico"
THEME_GREEN = (15, 118, 110, 255)


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "SOP-IGS brand asset builder"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def green_wordmark(source: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(source)).convert("RGBA")
    # Official asset has its slogan in the cyan lower band. Keep only the CHINT wordmark area.
    crop = image.crop((0, 0, image.width, round(image.height * 0.74)))
    output = Image.new("RGBA", crop.size, (0, 0, 0, 0))
    for y in range(crop.height):
        for x in range(crop.width):
            red, green, blue, alpha = crop.getpixel((x, y))
            white_mark = min(red, green, blue) > 180 and max(red, green, blue) - min(red, green, blue) < 55
            red_mark = red > 160 and green < 130 and blue < 160
            if alpha and (white_mark or red_mark):
                output.putpixel((x, y), THEME_GREEN)
    bounds = output.getbbox()
    if not bounds:
        raise RuntimeError("Could not isolate the official CHINT wordmark")
    output = output.crop(bounds)
    padded = Image.new("RGBA", (output.width + 12, output.height + 12), (0, 0, 0, 0))
    padded.alpha_composite(output, (6, 6))
    return padded


def green_favicon(source: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(source)).convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)
    pixels = image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata()
    opaque_colors = Counter(
        (red, green, blue)
        for red, green, blue, alpha in pixels
        if alpha > 180
    )
    background = opaque_colors.most_common(1)[0][0]
    output = Image.new("RGBA", image.size, (0, 0, 0, 0))
    for y in range(image.height):
        for x in range(image.width):
            red, green, blue, alpha = image.getpixel((x, y))
            distance = sum((value - base) ** 2 for value, base in zip((red, green, blue), background, strict=True)) ** 0.5
            if alpha > 20 and distance > 32:
                output.putpixel((x, y), (*THEME_GREEN[:3], alpha))
    if not ImageChops.difference(output, Image.new("RGBA", output.size)).getbbox():
        raise RuntimeError("Could not isolate the official CHINT favicon")
    return output


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    logo = download(LOGO_URL)
    favicon = download(FAVICON_URL)
    (OUTPUT / "chint-logo-source.png").write_bytes(logo)
    (OUTPUT / "chint-favicon-source.ico").write_bytes(favicon)
    green_wordmark(logo).save(OUTPUT / "chint-wordmark-green.png", optimize=True)
    green_favicon(favicon).save(
        OUTPUT / "favicon.ico",
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64)],
    )


if __name__ == "__main__":
    main()
