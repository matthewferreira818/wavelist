"""
Posts a product-spotlight tweet with a branded ad-card image, three times a
day (morning / afternoon / evening slots), featuring a different product each
time — then replies to its own tweet with the store link + a scan-to-shop QR
code card.

The workflow's cron fires at 13:00, 17:00 and 21:00 UTC; the slot is derived
from the current UTC hour, and the product pick walks the trend-ranked list
3 steps per day so no product repeats within a day and the whole catalog gets
featured over time. On catalog-refresh days the workflow skips the morning
slot only (the fresh-drops roundup covers it), keeping 3 product posts a day.

Optional env:
    SPOTLIGHT_OFFSET - integer added to the pick index (used by manual test runs)

Skips silently (exit 0) if the X_* secrets aren't configured. Images degrade
gracefully: if a card can't be built/uploaded, the tweet posts text-only.
"""

import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
PRODUCTS_FILE = HERE / "products.json"
LINK = "findhotstuff.com"
MAX_TWEET = 280

CREDS = ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]


def current_slot():
    """0 / 1 / 2 for the morning / afternoon / evening posting windows."""
    hour = datetime.now(timezone.utc).hour
    if hour < 15:
        return 0
    if hour < 19:
        return 1
    return 2


def pick_product():
    products = json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))
    ranked = sorted(products, key=lambda x: x.get("trendScore", 0), reverse=True)
    offset = int(os.environ.get("SPOTLIGHT_OFFSET") or 0)
    idx = (date.today().toordinal() * 3 + current_slot() + offset) % len(ranked)
    return ranked[idx]


def compose_spotlight(p):
    from generate_posts import ad_name, flavor, pick, HOOKS, TAGS

    name = ad_name(p.get("name", ""), p.get("category", ""))
    hook = pick(flavor(HOOKS, p.get("category", "*")), p["id"] + f"daily{current_slot()}")
    tags = flavor(TAGS, p.get("category", "*"))
    emoji = p.get("emoji", "\U0001F525")
    price = f"${float(p['price']):.2f}"

    tweet = (
        f"{hook} {emoji}\n"
        f"{name} — just {price} at HotsTuff \U0001F525\n"
        f"Grab it before it rotates out \U0001F440 {LINK}\n"
        f"{tags}"
    )
    if len(tweet) > MAX_TWEET:  # drop hashtags first if somehow too long
        tweet = tweet.rsplit("\n", 1)[0]
    return tweet[:MAX_TWEET]


def post(session, text, media_id=None, reply_to=None):
    payload = {"text": text}
    if media_id:
        payload["media"] = {"media_ids": [media_id]}
    if reply_to:
        payload["reply"] = {"in_reply_to_tweet_id": reply_to}
    return session.post("https://api.x.com/2/tweets", json=payload, timeout=30)


def main():
    missing = [c for c in CREDS if not os.environ.get(c)]
    if missing:
        print(f"X credentials not configured ({', '.join(missing)}) - skipping tweet.")
        return 0

    from requests_oauthlib import OAuth1Session

    from tweet_media import build_ad_card, build_qr_card, upload_media

    product = pick_product()
    tweet = compose_spotlight(product)
    print(f"Slot {current_slot()} spotlight:\n{tweet}")

    session = OAuth1Session(
        os.environ["X_API_KEY"],
        client_secret=os.environ["X_API_SECRET"],
        resource_owner_key=os.environ["X_ACCESS_TOKEN"],
        resource_owner_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )

    # branded product card — never let image trouble block the tweet
    media_id = None
    try:
        media_id = upload_media(session, build_ad_card(product))
    except Exception as exc:  # noqa: BLE001
        print(f"ad card skipped ({exc}) - posting text-only")

    resp = post(session, tweet, media_id=media_id)
    if resp.status_code == 402:
        # marker line consumed by the workflow's credit-watch step
        print("X_CREDITS_DEPLETED: tweets are paused until credits are topped up at console.x.com")
        return 0
    if resp.status_code not in (200, 201):
        print(f"Tweet failed (HTTP {resp.status_code}): {resp.text[:300]}")
        return 0  # never fail the workflow over a tweet
    tweet_id = resp.json().get("data", {}).get("id")
    print("Tweet posted:", tweet_id)

    # reply with the link + QR card so the shop is one scan away
    qr_id = None
    try:
        qr_id = upload_media(session, build_qr_card())
    except Exception as exc:  # noqa: BLE001
        print(f"QR card skipped ({exc}) - replying with link only")
    reply = post(session, f"Tap or scan to shop \U0001F447\nhttps://{LINK}/",
                 media_id=qr_id, reply_to=tweet_id)
    if reply.status_code in (200, 201):
        print("QR reply posted:", reply.json().get("data", {}).get("id"))
    else:
        print(f"QR reply failed (HTTP {reply.status_code}): {reply.text[:200]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
