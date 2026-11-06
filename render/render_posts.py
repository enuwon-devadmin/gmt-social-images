"""Render GMT product posts: brand headline + real product image + logo.

Reads a batch spec (JSON list). Each item:
  {"name": "genx-tee-001", "headline": "...", "sub": "...", "images": ["https://..."]}
One image = single product. Two to four images = grid (gift guide style).

Writes two files per item:
  images/<name>.png         1080x1350 (Instagram/Facebook feed, 4:5)
  images/<name>-tiktok.png  1080x1920 (TikTok photo mode, 9:16, text kept clear of TikTok UI)

Product images are downloaded at run time, so this runs in GitHub Actions
(the shop and Amazon image hosts are reachable there).
"""
import io
import json
import sys
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
OUT = HERE.parent / "images"
PEACH = (246, 231, 216)   # Palette 7 Peach Dust
OLIVE = (110, 112, 48)    # Palette 1 Dark Olive Green
JET = (26, 26, 26)        # Palette 3
DARK = (46, 46, 46)       # Palette 4
WHITE = (255, 255, 255)

HEAD_FONT = str(HERE / "fonts" / "BebasNeue-Regular.ttf")
BODY_FONT = str(HERE / "fonts" / "Montserrat[wght].ttf")


def font(path, size, weight=None):
    f = ImageFont.truetype(path, size)
    if weight is not None:
        try:
            f.set_variation_by_axes([weight])
        except Exception:
            pass
    return f


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "gmt-render/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return Image.open(io.BytesIO(r.read())).convert("RGB")


def wrap(draw, text, fnt, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=fnt) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit_text(draw, text, path, max_w, max_lines, start, minimum, weight=None):
    size = start
    while size >= minimum:
        f = font(path, size, weight)
        lines = wrap(draw, text, f, max_w)
        if len(lines) <= max_lines:
            return f, lines
        size -= 4
    f = font(path, minimum, weight)
    return f, wrap(draw, text, f, max_w)


def draw_lines(draw, lines, fnt, y, width, fill, gap):
    for ln in lines:
        w = draw.textlength(ln, font=fnt)
        draw.text(((width - w) / 2, y), ln, font=fnt, fill=fill)
        y += fnt.size + gap
    return y


def trim_white(im, tol=245):
    """Crop the plain white margin around Printful mockups so the product fills the card."""
    gray = im.convert("L").point(lambda p: 255 if p < tol else 0)
    box = gray.getbbox()
    if not box:
        return im
    pad = int(max(im.size) * 0.03)
    l, t, r, b = box
    return im.crop((max(0, l - pad), max(0, t - pad), min(im.width, r + pad), min(im.height, b + pad)))


def paste_fit(canvas, im, box):
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    scale = min(bw / im.width, bh / im.height)
    im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)
    canvas.paste(im, (x0 + (bw - im.width) // 2, y0 + (bh - im.height) // 2))


def product_panel(images, w, h):
    """White rounded card holding one product, or a 2x2 / 1x2 grid."""
    card = Image.new("RGB", (w, h), WHITE)
    n = len(images)
    if n == 1:
        cells = [(0, 0, w, h)]
    elif n == 2:
        cells = [(0, 0, w // 2, h), (w // 2, 0, w, h)]
    elif n == 3:
        cells = [(0, 0, w // 2, h // 2), (w // 2, 0, w, h // 2), (w // 4, h // 2, 3 * w // 4, h)]
    else:
        cells = [(0, 0, w // 2, h // 2), (w // 2, 0, w, h // 2), (0, h // 2, w // 2, h), (w // 2, h // 2, w, h)]
    pad = 24 if n > 1 else 36
    for im, (x0, y0, x1, y1) in zip(images, cells):
        paste_fit(card, trim_white(im), (x0 + pad, y0 + pad, x1 - pad, y1 - pad))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=36, fill=255)
    return card, mask


def render(item, products, size, top_pad, bottom_pad):
    W, H = size
    canvas = Image.new("RGB", (W, H), PEACH)
    d = ImageDraw.Draw(canvas)
    margin = 70

    y = top_pad
    hf, hlines = fit_text(d, item["headline"].upper(), HEAD_FONT, W - 2 * margin, 2, 112, 72)
    y = draw_lines(d, hlines, hf, y, W, JET, 6)

    sub = item.get("sub", "").strip()
    if sub:
        sf, slines = fit_text(d, sub, BODY_FONT, W - 2 * margin, 2, 40, 30, weight=500)
        y = draw_lines(d, slines, sf, y + 14, W, DARK, 10)

    logo = Image.open(HERE / "assets" / "logo.png").convert("RGB")
    logo_h = 84
    logo = logo.resize((int(logo.width * logo_h / logo.height), logo_h), Image.LANCZOS)
    logo_y = H - bottom_pad - logo_h
    rule_y = logo_y - 34
    d.rectangle((margin, rule_y, W - margin, rule_y + 5), fill=OLIVE)
    canvas.paste(logo, ((W - logo.width) // 2, logo_y))

    panel_top = y + 34
    panel_bottom = rule_y - 34
    card, mask = product_panel(products, W - 2 * margin, panel_bottom - panel_top)
    canvas.paste(card, (margin, panel_top), mask)
    return canvas


def main(spec_path):
    items = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    OUT.mkdir(exist_ok=True)
    only = set(sys.argv[2].split(",")) if len(sys.argv) > 2 and sys.argv[2] else None
    failed = 0
    for item in items:
        if only and item["name"] not in only:
            continue
        try:
            products = [fetch(u) if u.startswith("http") else Image.open(u).convert("RGB") for u in item["images"]]
            render(item, products, (1080, 1350), 80, 56).save(OUT / f"{item['name']}.png", optimize=True)
            # TikTok: keep text below the top bar and the product above the caption/button area.
            render(item, products, (1080, 1920), 230, 430).save(OUT / f"{item['name']}-tiktok.png", optimize=True)
            print("rendered", item["name"])
        except Exception as e:  # keep going so one bad image does not block the batch
            failed += 1
            print(f"::error title=Render failed::{item['name']}: {e}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main(sys.argv[1])
