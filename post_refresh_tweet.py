"""
Posts one "fresh drops" tweet after each catalog refresh, via the official
X (Twitter) API v2 using the store's own developer credentials.

Runs in GitHub Actions after refresh_products.py. Skips silently (exit 0) if
the X_* secrets aren't configured yet, so the workflow never breaks.

Required env vars (GitHub Actions secrets):
    X_API_KEY, X_API_SECRET            - the app's consumer keys
    X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET - user tokens for @<store account>,
        generated AFTER setting the app's permissions to "Read and write"

Keeps volume to ~1 tweet per 3-day refresh (~10/month) - well inside the free
tier and far below anything spammy.
"""

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
PRODUCTS_FILE = HERE / "products.json"
LINK = "findhotstuff.com"
MAX_TWEET = 280

CREDS = ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]


def ad_name_for(p):
    # reuse the same clean short names the ad copy uses
    from generate_posts import ad_name
    return ad_name(p.get("name", ""), p.get("category", ""))


def compose_tweet(products):
    ranked = sorted(products, key=lambda x: x.get("trendScore", 0), reverse=True)
    lines = ["Fresh drops just landed at HotsTuff \U0001F525"]
    for p in ranked[:3]:
        name = ad_name_for(p)
        lines.append(f"{p.get('emoji', '\U0001F6CD️')} {name} – ${float(p['price']):.2f}")
    lines.append(f"Rotating out in a few days \U0001F440 {LINK}")
    tweet = "\n".join(lines)
    # trim product lines if somehow over the limit
    while len(tweet) > MAX_TWEET and len(lines) > 3:
        lines.pop(-2)
        tweet = "\n".join(lines)
    return tweet[:MAX_TWEET]


def main():
    missing = [c for c in CREDS if not os.environ.get(c)]
    if missing:
        print(f"X credentials not configured ({', '.join(missing)}) - skipping tweet.")
        return 0

    from requests_oauthlib import OAuth1Session

    products = json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))
    tweet = compose_tweet(products)
    print("Tweeting:\n" + tweet)

    session = OAuth1Session(
        os.environ["X_API_KEY"],
        client_secret=os.environ["X_API_SECRET"],
        resource_owner_key=os.environ["X_ACCESS_TOKEN"],
        resource_owner_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )
    resp = session.post("https://api.x.com/2/tweets", json={"text": tweet}, timeout=30)
    if resp.status_code in (200, 201):
        print("Tweet posted:", resp.json().get("data", {}).get("id"))
        return 0
    if resp.status_code == 402:
        # marker line consumed by the workflow's credit-watch step
        print("X_CREDITS_DEPLETED: tweets are paused until credits are topped up at console.x.com")
        return 0
    # Don't fail the whole refresh workflow over a tweet - log and move on.
    print(f"Tweet failed (HTTP {resp.status_code}): {resp.text[:300]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
