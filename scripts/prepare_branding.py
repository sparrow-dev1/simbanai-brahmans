"""Prepare branding assets from the unchanged supplied logo (Pillow required).

The user approved a deterministic cutout after two imagegen extractions failed
visual review. This removes the green matte without redrawing the artwork.
Run: python scripts/prepare_branding.py
"""

import base64
from pathlib import Path
from statistics import median

from PIL import Image, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
GREEN = (47, 93, 58, 255)


def transparent_copy(source):
    pixels = list(source.get_flattened_data())
    ink = [p for p in pixels if min(p) > 230]
    foreground = tuple(int(median(p[i] for p in ink)) for i in range(3))
    # Estimate the local matte from dark green neighbours, excluding the ink.
    anchors = [255 if min(p) < 45 and p[1] > p[0] and p[1] > p[2] else 0 for p in pixels]
    weights = Image.new("L", source.size)
    weights.putdata(anchors)
    weights = list(weights.filter(ImageFilter.GaussianBlur(5)).get_flattened_data())
    channels = []
    for i in range(3):
        channel = Image.new("L", source.size)
        channel.putdata([p[i] if weight else 0 for p, weight in zip(pixels, anchors)])
        channels.append(list(channel.filter(ImageFilter.GaussianBlur(5)).get_flattened_data()))
    result = []
    for index, pixel in enumerate(pixels):
        if min(pixel) <= 60:
            result.append((*foreground, 0))
            continue
        weight = weights[index]
        background = tuple(channels[i][index] * 255 / weight for i in range(3)) if weight else (50, 72, 23)
        direction = tuple(foreground[i] - background[i] for i in range(3))
        denominator = sum(v * v for v in direction)
        opacity = sum((pixel[i] - background[i]) * direction[i] for i in range(3)) / denominator if denominator else 1
        opacity = max(0, min(1, opacity))
        alpha = round(opacity * 255) if opacity >= 0.05 else 0
        # Preserve the source's white colour variations on opaque strokes;
        # remove the green contamination from antialiased boundary pixels.
        colour = pixel if alpha >= 250 and min(pixel) > 230 else foreground
        result.append((*colour, alpha))
    image = Image.new("RGBA", source.size)
    image.putdata(result)
    return image


def main():
    source = Image.open(STATIC / "company-logo.png").convert("RGB")
    logo = transparent_copy(source)
    logo.save(STATIC / "company-logo-transparent.png", optimize=True)
    # The supplied artwork's emblem occupies the upper 72%; lettering starts
    # below it. Crop only the emblem's nontransparent bounds.
    upper = logo.crop((0, 0, logo.width, round(logo.height * 0.72)))
    bounds = upper.getchannel("A").getbbox()
    emblem = upper.crop(bounds)
    emblem.save(STATIC / "cattle-emblem-transparent.png", optimize=True)
    encoded = base64.b64encode((STATIC / "cattle-emblem-transparent.png").read_bytes()).decode("ascii")
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <rect width="512" height="512" fill="#2F5D3A"/>
  <image href="data:image/png;base64,{encoded}" x="20" y="20" width="472" height="472" preserveAspectRatio="xMidYMid meet"/>
</svg>
'''
    (STATIC / "favicon-v6.svg").write_text(svg, encoding="utf-8")
    (STATIC / "icon.svg").write_text(svg, encoding="utf-8")
    icons = {}
    for size in (16, 32, 192, 512):
        canvas = Image.new("RGBA", (size, size), GREEN)
        mark = emblem.copy()
        margin = round(size * 20 / 512)
        mark.thumbnail((size - 2 * margin, size - 2 * margin), Image.Resampling.LANCZOS)
        canvas.alpha_composite(mark, ((size - mark.width) // 2, (size - mark.height) // 2))
        icons[size] = canvas
        if size in (192, 512):
            canvas.save(STATIC / f"icon-{size}-v6.png", optimize=True)
        else:
            preview = ROOT / "test-output" / f"favicon-{size}.png"
            preview.parent.mkdir(parents=True, exist_ok=True)
            canvas.save(preview)
    icons[32].save(STATIC / "favicon-v6.ico", sizes=[(16, 16), (32, 32)], bitmap_format="png")
    print("Transparent logo:", logo.size, "alpha", logo.getchannel("A").getextrema())
    print("Cattle emblem bounds:", bounds, "without company lettering")
    print("Saved SVG/ICO favicon and 192/512-pixel PWA icons in static/.")


if __name__ == "__main__":
    main()
