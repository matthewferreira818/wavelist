"""
Posts one product-spotlight tweet per day, featuring a different product from
the current catalog each time, via the official X API v2.

The 3-day refresh workflow already tweets a "fresh drops just landed" roundup
on rotation days — that IS the "items refreshed!" advert. The daily workflow
that runs this script skips those days (checked in the workflow), so the
account gets exactly one tweet a day:
    day 1: spotlight A -> day 2: spotlight B -> day 3: fresh-drops roundup -> ...

Skips silently (exit 0) if the X_* secrets aren't configured.
"""

import json
import os
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent
PRODUCTS_FILE = HERE / "products.json"
LINK = "findhotstuff.com"
MAX_TWEET = 280

CREDS = ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]


def compose_spotlight():
    from generate_posts import ad_name, flavor, pick, HOOKS, TAGS

    products = json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))
    ranked = sorted(products, key=lambda x: x.get("trendScore", 0), reverse=True)

    # Different product every day: walk the trend-ranked list by day number, so
    # consecutive days never repeat and the whole catalog gets featured over time.
    p = ranked[date.today().toordinal() % len(ranked)]

    name = ad_name(p.get("name", ""), p.get("category", ""))
    hook = pick(flavor(HOOKS, p.get("category", "*")), p["id"] + "daily")
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


def main():
    missing = [c for c in CREDS if not os.environ.get(c)]
    if missing:
        print(f"X credentials not configured ({', '.join(missing)}) - skipping tweet.")
        return 0

    from requests_oauthlib import OAuth1Session

    tweet = compose_spotlight()
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
    elif resp.status_code == 402:
        # marker line consumed by the workflow's credit-watch step
        print("X_CREDITS_DEPLETED: tweets are paused until credits are topped up at console.x.com")
    else:
        print(f"Tweet failed (HTTP {resp.status_code}): {resp.text[:300]}")
    return 0  # never fail the workflow over a tweet


if __name__ == "__main__":
    sys.exit(main())
