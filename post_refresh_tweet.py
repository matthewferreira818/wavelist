"""
Posts one "fresh drops" tweet after each catalog refresh, with branded ad-card
images for the top products attached, then replies to it with the store link +
a scan-to-shop QR code card.

Runs in GitHub Actions after refresh_products.py. Skips silently (exit 0) if
the X_* secrets aren't configured, so the workflow never breaks. Images
degrade gracefully: if cards can't be built/uploaded the tweet posts text-only.

Required env vars (GitHub Actions secrets):
    X_API_KEY, X_API_SECRET            - the app's consumer keys
    X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET - user tokens for @<store account>,
        generated AFTER setting the app's permissions to "Read and write"
"""

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
PRODUCTS_FILE = HERE / "products.json"
LINK = "findhotstuff.com"
MAX_TWEET = 280
FEATURED = 3  # products shown in the tweet text and attached as cards


def ad_name_for(p):
    # reuse the same clean short names the ad copy uses
    from generate_posts import ad_name
    return ad_name(p.get("name", ""), p.get("category", ""))


def compose_tweet(ranked):
    lines = ["Fresh drops just landed at HotsTuff \U0001F525"]
    for p in ranked[:FEATURED]:
        name = ad_name_for(p)
        lines.append(f"{p.get('emoji', '\U0001F6CD️')} {name} – ${float(p['price']):.2f}")
    lines.append(f"Rotating out in a few days \U0001F440 {LINK}")
    tweet = "\n".join(lines)
    # trim product lines if somehow over the limit
    while len(tweet) > MAX_TWEET and len(lines) > 3:
        lines.pop(-2)
        tweet = "\n".join(lines)
    return tweet[:MAX_TWEET]


def post(session, text, media_ids=None, reply_to=None):
    payload = {"text": text}
    if media_ids:
        payload["media"] = {"media_ids": media_ids}
    if reply_to:
        payload["reply"] = {"in_reply_to_tweet_id": reply_to}
    return session.post("https://api.x.com/2/tweets", json=payload, timeout=30)


def main():
    creds = ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]
    missing = [c for c in creds if not os.environ.get(c)]
    if missing:
        print(f"X credentials not configured ({', '.join(missing)}) - skipping tweet.")
        return 0

    from requests_oauthlib import OAuth1Session

    from tweet_media import build_ad_card, build_qr_card, upload_media

    products = json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))
    ranked = sorted(products, key=lambda x: x.get("trendScore", 0), reverse=True)
    tweet = compose_tweet(ranked)
    print("Tweeting:\n" + tweet)

    session = OAuth1Session(
        os.environ["X_API_KEY"],
        client_secret=os.environ["X_API_SECRET"],
        resource_owner_key=os.environ["X_ACCESS_TOKEN"],
        resource_owner_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )

    # ad cards for the featured products — never block the tweet over images
    media_ids = []
    for p in ranked[:FEATURED]:
        try:
            media_id = upload_media(session, build_ad_card(p))
            if media_id:
                media_ids.append(media_id)
        except Exception as exc:  # noqa: BLE001
            print(f"card for {p.get('id')} skipped ({exc})")

    resp = post(session, tweet, media_ids=media_ids or None)
    if resp.status_code == 402:
        # marker line consumed by the workflow's credit-watch step
        print("X_CREDITS_DEPLETED: tweets are paused until credits are topped up at console.x.com")
        return 0
    if resp.status_code not in (200, 201):
        # Don't fail the whole refresh workflow over a tweet - log and move on.
        print(f"Tweet failed (HTTP {resp.status_code}): {resp.text[:300]}")
        return 0
    tweet_id = resp.json().get("data", {}).get("id")
    print("Tweet posted:", tweet_id)

    # reply with the link + QR card so the shop is one scan away
    qr_id = None
    try:
        qr_id = upload_media(session, build_qr_card())
    except Exception as exc:  # noqa: BLE001
        print(f"QR card skipped ({exc}) - replying with link only")
    reply = post(session, f"Tap or scan to shop \U0001F447\nhttps://{LINK}/",
                 media_ids=[qr_id] if qr_id else None, reply_to=tweet_id)
    if reply.status_code in (200, 201):
        print("QR reply posted:", reply.json().get("data", {}).get("id"))
    else:
        print(f"QR reply failed (HTTP {reply.status_code}): {reply.text[:200]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
