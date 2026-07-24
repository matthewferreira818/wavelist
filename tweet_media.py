"""
Shared helpers for attaching images to the store's automated tweets.

- build_ad_card(product): downloads the product photo and composes a square
  branded ad card (photo + name + price + site URL) as PNG bytes.
- build_qr_card(): renders the store's QR code on a small branded card,
  for posting as a reply under each ad tweet.
- upload_media(session, png): uploads PNG bytes to X and returns a media id
  (tries the v2 endpoint first, falls back to the legacy v1.1 one).

Everything degrades gracefully: callers treat None / exceptions as "post the
tweet without an image" — media must never break the posting workflow.

Run directly to render sample cards for a visual check without posting:
    python tweet_media.py out_dir
"""

import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
SITE = "findhotstuff.com"
SITE_URL = "https://findhotstuff.com/"

BG = "#fff9f2"        # site background
ACCENT = "#e11d48"    # brand red
INK = "#222222"
MUTED = "#8a8177"

CARD = 1080           # square ad card edge

# bold/regular font locations on the GitHub runner (Ubuntu) and Windows
_FONTS = {
    True: ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
           r"C:\Windows\Fonts\arialbd.ttf"],
    False: ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            r"C:\Windows\Fonts\arial.ttf"],
}


def _font(size, bold=False):
    from PIL import ImageFont
    for path in _FONTS[bold]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _bezier(p0, p1, p2, p3, steps=40):
    pts = []
    for i in range(steps + 1):
        t = i / steps
        mt = 1 - t
        pts.append((mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0],
                    mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]))
    return pts


def _flame_points(x, y, w, h, flip=False):
    """Brand flame silhouette (same path as the X logo) scaled into a box."""
    segs = [
        ((0.58, 0.00), (0.42, 0.10), (0.28, 0.22), (0.20, 0.36)),
        ((0.20, 0.36), (0.12, 0.50), (0.06, 0.60), (0.08, 0.72)),
        ((0.08, 0.72), (0.10, 0.88), (0.28, 1.00), (0.50, 1.00)),
        ((0.50, 1.00), (0.74, 1.00), (0.92, 0.88), (0.92, 0.68)),
        ((0.92, 0.68), (0.92, 0.55), (0.84, 0.50), (0.80, 0.40)),
        ((0.80, 0.40), (0.76, 0.30), (0.72, 0.26), (0.74, 0.18)),
        ((0.74, 0.18), (0.72, 0.10), (0.66, 0.04), (0.58, 0.00)),
    ]
    pts = []
    for p0, p1, p2, p3 in segs:
        pts.extend(_bezier(p0, p1, p2, p3)[:-1])
    if flip:
        pts = [(1 - px, py) for px, py in pts]
    return [(x + px * w, y + py * h) for px, py in pts]


def draw_flame(draw, x, y, h, outer=ACCENT, inner="#f59e0b", core=BG):
    """Draw the layered brand flame at height h; returns its width."""
    w = h * 0.84
    draw.polygon(_flame_points(x, y, w, h), fill=outer)
    iw, ih = w * 0.60, h * 0.55
    draw.polygon(_flame_points(x + (w - iw) / 2, y + h - ih * 1.02, iw, ih, flip=True),
                 fill=inner)
    cw, ch = w * 0.32, h * 0.28
    draw.polygon(_flame_points(x + (w - cw) / 2, y + h - ch * 1.06, cw, ch), fill=core)
    return w


def _fit_text(draw, text, font_size, bold, max_width):
    """Return (text, font) shrunk/ellipsized until it fits max_width."""
    font = _font(font_size, bold)
    while draw.textlength(text, font=font) > max_width and font_size > 24:
        font_size -= 4
        font = _font(font_size, bold)
    while draw.textlength(text, font=font) > max_width and len(text) > 8:
        text = text[:-2].rstrip() + "…"
    return text, font


def build_ad_card(product):
    """Compose the branded product card. Returns PNG bytes (or raises)."""
    import requests
    from PIL import Image, ImageDraw

    from generate_posts import ad_name

    canvas = Image.new("RGB", (CARD, CARD), BG)
    draw = ImageDraw.Draw(canvas)

    # header: flame + wordmark left, site right
    fw = draw_flame(draw, 44, 26, 84)
    draw.text((44 + fw + 16, 34), "HotsTuff", font=_font(68, True), fill=ACCENT)
    site_font = _font(32)
    draw.text((CARD - 48 - draw.textlength(SITE, font=site_font), 62),
              SITE, font=site_font, fill=MUTED)

    # product photo centered in the middle band
    photo_box = (48, 150, CARD - 48, 820)
    url = product.get("image")
    if url:
        resp = requests.get(url, timeout=25)
        resp.raise_for_status()
        photo = Image.open(io.BytesIO(resp.content)).convert("RGB")
        photo.thumbnail((photo_box[2] - photo_box[0], photo_box[3] - photo_box[1]))
        px = photo_box[0] + (photo_box[2] - photo_box[0] - photo.width) // 2
        py = photo_box[1] + (photo_box[3] - photo_box[1] - photo.height) // 2
        canvas.paste(photo, (px, py))

    # product name
    name = ad_name(product.get("name", ""), product.get("category", ""))
    name, name_font = _fit_text(draw, name, 46, True, CARD - 96)
    draw.text(((CARD - draw.textlength(name, font=name_font)) // 2, 848),
              name, font=name_font, fill=INK)

    # price pill
    price = f"${float(product['price']):.2f}"
    price_font = _font(46, True)
    pw = draw.textlength(price, font=price_font)
    pill_w = pw + 76
    pill = ((CARD - pill_w) // 2, 924, (CARD + pill_w) // 2, 1000)
    draw.rounded_rectangle(pill, radius=38, fill=ACCENT)
    draw.text((pill[0] + 38, 936), price, font=price_font, fill="#ffffff")

    # footer
    foot = "New drops every 3 days"
    foot_font = _font(30)
    draw.text(((CARD - draw.textlength(foot, font=foot_font)) // 2, 1022),
              foot, font=foot_font, fill=MUTED)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


def build_qr_card():
    """Compose the scan-to-shop QR reply card. Returns PNG bytes."""
    import segno
    from PIL import Image, ImageDraw

    qr_buf = io.BytesIO()
    segno.make(SITE_URL, error="m").save(
        qr_buf, kind="png", scale=24, border=2, dark="#111111", light="#ffffff")
    qr = Image.open(qr_buf).convert("RGB")
    if qr.width > 660:
        qr = qr.resize((660, 660), Image.NEAREST)

    canvas = Image.new("RGB", (900, 1000), "#ffffff")
    draw = ImageDraw.Draw(canvas)
    wm_font = _font(58, True)
    fh = 74
    total = fh * 0.84 + 14 + draw.textlength("HotsTuff", font=wm_font)
    x0 = (900 - total) // 2
    fw = draw_flame(draw, x0, 32, fh, core="#ffffff")
    draw.text((x0 + fw + 14, 42), "HotsTuff", font=wm_font, fill=ACCENT)
    canvas.paste(qr, ((900 - qr.width) // 2, 140))
    scan_font = _font(48, True)
    draw.text(((900 - draw.textlength("Scan to shop", font=scan_font)) // 2, 838),
              "Scan to shop", font=scan_font, fill=INK)
    site_font = _font(40)
    draw.text(((900 - draw.textlength(SITE, font=site_font)) // 2, 912),
              SITE, font=site_font, fill=ACCENT)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


def upload_media(session, png_bytes):
    """Upload PNG bytes to X; returns a media id string or None."""
    files = {"media": ("card.png", png_bytes, "image/png")}
    for url in ("https://api.x.com/2/media/upload",
                "https://upload.twitter.com/1.1/media/upload.json"):
        try:
            resp = session.post(url, files=files,
                                data={"media_category": "tweet_image"}, timeout=60)
        except Exception as exc:  # noqa: BLE001 - never break posting over media
            print(f"media upload error at {url}: {exc}")
            continue
        if resp.status_code in (200, 201):
            body = resp.json()
            media_id = (body.get("data") or {}).get("id") or body.get("media_id_string")
            if media_id:
                return str(media_id)
        print(f"media upload {url} -> HTTP {resp.status_code}: {resp.text[:200]}")
    return None


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE
    products = json.loads((HERE / "products.json").read_text(encoding="utf-8"))
    sample = max(products, key=lambda p: p.get("trendScore", 0))
    (out / "sample-ad-card.png").write_bytes(build_ad_card(sample))
    (out / "sample-qr-card.png").write_bytes(build_qr_card())
    print(f"wrote sample-ad-card.png + sample-qr-card.png to {out}")
