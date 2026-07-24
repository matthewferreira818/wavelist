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

    # header: wordmark left, site right
    draw.text((48, 34), "HotsTuff", font=_font(68, True), fill=ACCENT)
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
    draw.text(((900 - draw.textlength("HotsTuff", font=wm_font)) // 2, 42),
              "HotsTuff", font=wm_font, fill=ACCENT)
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
