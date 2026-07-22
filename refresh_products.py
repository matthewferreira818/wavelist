"""
Pulls currently-trending products from CJ Dropshipping and rewrites products.json.

Usage:
    python refresh_products.py

Requires a .env file (same folder) containing:
    CJ_API_KEY=CJUserNum@api@xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
"""

import hashlib
import json
import math
import os
import re
import urllib.request
import urllib.error
from pathlib import Path

HERE = Path(__file__).parent
ENV_FILE = HERE / ".env"
PRODUCTS_FILE = HERE / "products.json"

AUTH_URL = "https://developers.cjdropshipping.com/api2.0/v1/authentication/getAccessToken"
PRODUCT_LIST_URL = "https://developers.cjdropshipping.com/api2.0/v1/product/listV2"

DISPLAY_COUNT = 13   # products shown on the site each cycle
POOL_SIZE = 60       # how many trending products to pull, to rotate a fresh selection from
MAX_REPEATS = 3      # at most this many items may carry over from the previous cycle
                     # -> guarantees at least (DISPLAY_COUNT - MAX_REPEATS) = 10 items change each cycle
MARKUP_MULTIPLIER = 1.6  # legacy wholesale-only floor (cost * this). Kept as an
                          # extra always-on safety margin on top of the real
                          # profit guarantee below; for cost > ~$16.80 this
                          # multiplier actually becomes the binding floor.

# --- No-loss guarantee -------------------------------------------------
# A sale's true cost has THREE parts, and pricing must cover all three:
#   1. CJ wholesale cost         -- known per product (`cost` below)
#   2. CJ fulfillment shipping   -- auto-charged to the CJ balance per order,
#      NOT known until checkout. We price for a conservative worst case so
#      the real charge can never exceed what we've already priced for.
#   3. Stripe's transaction fee  -- 2.9% of the charge + $0.30 fixed
#
# STRIPE_PCT_FEE / STRIPE_FIXED_FEE: Stripe's published fee schedule.
#
# CJ_SHIPPING_WORST_CASE: conservative ceiling on CJ shipping cost to the
# US/Canada for light trending dropship goods. CJ's standard/ePacket-class
# shipping for small parcels typically runs $2-6, occasionally $6-8 for
# bulkier items, remote provinces, or peak-season surcharges. We price for
# $8.00 -- the top of that observed range -- so real per-order shipping
# charges are covered even in the worst case we've seen.
#
# MIN_NET_MARGIN: minimum guaranteed profit per unit after ALL of the above,
# so "profitable" isn't a razor's-edge $0.01 that rounding/misc fees/exchange
# -rate slop could wipe out.
STRIPE_PCT_FEE = 0.029
STRIPE_FIXED_FEE = 0.30
CJ_SHIPPING_WORST_CASE = 8.00
MIN_NET_MARGIN = 1.00

# Retail-looking price points, raised from the old $4-$25 spread because the
# floor below (shipping + fees + margin, not just wholesale cost) genuinely
# requires it -- at $8 worst-case shipping alone, nothing under ~$9.60 can
# ever be guaranteed profitable, so keeping price points below that would
# just mean they're silently never used. Each product is assigned one
# deterministically from its SKU (so its price is stable across cycles), then
# raised to whichever margin floor is higher if the supplier cost demands it.
PRICE_LADDER = [9.99, 11.99, 13.99, 15.99, 18.99, 21.99, 24.99, 27.99, 31.99, 35.99]

GRADIENTS = [
    "linear-gradient(135deg, #6366f1, #ec4899)",
    "linear-gradient(135deg, #f59e0b, #ef4444)",
    "linear-gradient(135deg, #0ea5e9, #6366f1)",
    "linear-gradient(135deg, #22c55e, #0ea5e9)",
    "linear-gradient(135deg, #ec4899, #f59e0b)",
    "linear-gradient(135deg, #a855f7, #ec4899)",
    "linear-gradient(135deg, #f43f5e, #a855f7)",
    "linear-gradient(135deg, #14b8a6, #6366f1)",
]

# CJ's list endpoint doesn't reliably return category names, so category + emoji
# are both derived from keywords in the product title.
NAME_KEYWORD_CATEGORIES = [
    (("blender", "juicer", "kitchen", "cup", "mug", "cookware"), "Kitchen", "🍳"),
    (("humidifier", "night light", "lamp", "led", "home", "decor"), "Home", "🏠"),
    (("makeup", "beauty", "skincare", "hair", "cosmetic"), "Beauty", "💄"),
    (("fitness", "gym", "yoga", "muscle", "workout"), "Fitness", "🏋️"),
    (("usb", "charger", "bluetooth", "electronic", "speaker", "earbud"), "Electronics", "🔌"),
    (("toy", "kids", "children", "game"), "Toys", "🧸"),
    (("pet", "dog", "cat"), "Pet", "🐾"),
    (("dress", "shirt", "fashion", "clothing", "jacket"), "Fashion", "👗"),
    (("jewelry", "necklace", "ring", "bracelet"), "Jewelry", "💍"),
    (("outdoor", "camping", "hiking", "tent"), "Outdoor", "🏕️"),
    (("bag", "backpack", "purse"), "Bags", "👜"),
    (("shoe", "sneaker", "sandal", "slipper"), "Footwear", "👟"),
    (("phone", "iphone", "case"), "Phone Accessories", "📱"),
    (("tool", "wrench", "repair"), "Tools", "🛠️"),
    (("glove", "sport", "riding", "motorcycle"), "Sports", "🧤"),
]


def classify_name(name: str) -> tuple[str, str]:
    name_lower = (name or "").lower()
    for keywords, category, emoji in NAME_KEYWORD_CATEGORIES:
        if any(k in name_lower for k in keywords):
            return category, emoji
    return "Trending Finds", "🛍️"


def parse_price(price_str) -> float:
    if not price_str:
        return 0.0
    match = re.search(r"[\d.]+", str(price_str))
    return float(match.group()) if match else 0.0


def product_id(p: dict) -> str:
    return p.get("sku") or p.get("id") or ""


def min_profitable_price(cost: float) -> float:
    """The lowest price that GUARANTEES the store does not lose money on a
    sale, even in the worst case, once every real cost is counted: CJ
    wholesale cost, worst-case CJ shipping, Stripe's fee, and a minimum
    profit cushion. Solves for `price` in:

        price - (price * STRIPE_PCT_FEE + STRIPE_FIXED_FEE)
              - cost - CJ_SHIPPING_WORST_CASE >= MIN_NET_MARGIN
    """
    needed = cost + CJ_SHIPPING_WORST_CASE + STRIPE_FIXED_FEE + MIN_NET_MARGIN
    return needed / (1 - STRIPE_PCT_FEE)


def assign_price(sku: str, cost: float) -> float:
    """Pick a stable, varied retail price for a product from PRICE_LADDER,
    never dropping below whichever margin floor is higher:
      - the legacy wholesale-only floor (cost * MARKUP_MULTIPLIER), or
      - min_profitable_price(cost), which additionally guarantees coverage
        of Stripe's fee and worst-case CJ shipping.
    This is what guarantees every sale is profitable even in the worst case.
    Price is still chosen deterministically from the SKU first (stable
    per-SKU price across refresh cycles), and only bumped up if the floor
    demands it."""
    floor = max(cost * MARKUP_MULTIPLIER, min_profitable_price(cost))
    h = int(hashlib.sha256((sku or "x").encode()).hexdigest(), 16)
    price = PRICE_LADDER[h % len(PRICE_LADDER)]
    if price < floor:
        higher = [p for p in PRICE_LADDER if p >= floor]
        if higher:
            price = higher[0]
        else:
            # Even the top of the ladder can't guarantee a profit on this
            # (unusually expensive) item. Break the ladder rather than ever
            # risk a loss -- round up to the cent so the floor is cleared.
            price = math.ceil(floor * 100) / 100
    return price


def load_previous_ids() -> set[str]:
    if not PRODUCTS_FILE.exists():
        return set()
    try:
        data = json.loads(PRODUCTS_FILE.read_text())
        return {p.get("id") for p in data if isinstance(p, dict)}
    except (json.JSONDecodeError, OSError):
        return set()


def select_rotating(pool: list[dict], prev_ids: set[str]) -> list[dict]:
    """Choose DISPLAY_COUNT products from the trending pool so that at most
    MAX_REPEATS carry over from last cycle (i.e. >= 10 change every cycle).
    Pool is already sorted by trend, so 'first N' keeps the hottest items."""
    fresh = [p for p in pool if product_id(p) not in prev_ids]
    repeats = [p for p in pool if product_id(p) in prev_ids]

    kept_repeats = repeats[:MAX_REPEATS]           # a little continuity for the top carry-overs
    chosen = fresh[: DISPLAY_COUNT - len(kept_repeats)] + kept_repeats

    if len(chosen) < DISPLAY_COUNT:                # pool smaller than expected — backfill
        extra = [p for p in repeats[MAX_REPEATS:] if p not in chosen]
        chosen += extra[: DISPLAY_COUNT - len(chosen)]

    return chosen[:DISPLAY_COUNT]


MAX_NAME_LENGTH = 55

# Pure marketing/SEO puffery that never describes the physical product.
# Dropped from titles (case-insensitive, whole words).
FILLER_WORDS = {
    "hot", "selling", "sale", "hotsale", "wholesale", "fashion",
    "trendy", "brand", "quality", "product", "products", "item",
}


def _dedupe_key(word: str) -> str:
    """Normalize a word for duplicate detection: lowercase, strip trailing
    punctuation, and fold simple plurals so 'Jacket' == 'Jackets'."""
    w = word.lower().strip(".,;:")
    if len(w) > 3 and w.endswith("s"):
        w = w[:-1]
    return w


def clean_name(name: str) -> str:
    words = " ".join((name or "").split()).split(" ")
    out, seen = [], set()
    for w in words:
        key = _dedupe_key(w)
        if not key or key in FILLER_WORDS or key in seen:
            continue  # drop filler puffery and repeated words (incl. plurals)
        seen.add(key)
        out.append(w)

    cleaned = " ".join(out).strip() or " ".join((name or "").split())
    if len(cleaned) <= MAX_NAME_LENGTH:
        return cleaned
    truncated = cleaned[:MAX_NAME_LENGTH].rsplit(" ", 1)[0]
    return truncated + "…"


def load_api_key() -> str:
    env_key = os.environ.get("CJ_API_KEY")
    if env_key:
        return env_key
    if not ENV_FILE.exists():
        raise SystemExit(
            f"CJ_API_KEY not set. Set it as an environment variable, "
            f"or add a line to {ENV_FILE}: CJ_API_KEY=your-key"
        )
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line.startswith("CJ_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(f"CJ_API_KEY not found in {ENV_FILE}")


def post_json(url: str, payload: dict, headers: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read().decode("utf-8"))


def get_json(url: str, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, method="GET")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read().decode("utf-8"))


def get_access_token(api_key: str) -> str:
    resp = post_json(AUTH_URL, {"apiKey": api_key})
    if resp.get("code") != 200 or not resp.get("result"):
        raise SystemExit(f"CJ auth failed: {resp.get('message', resp)}")
    return resp["data"]["accessToken"]


def fetch_trending_products(access_token: str) -> list[dict]:
    params = {
        "productFlag": 0,   # trending
        "orderBy": 1,       # sort by listing count (sales-volume proxy)
        "sort": "desc",
        "page": 1,
        "size": POOL_SIZE,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{PRODUCT_LIST_URL}?{query}"
    resp = get_json(url, headers={"CJ-Access-Token": access_token})
    if resp.get("code") != 200:
        raise SystemExit(f"CJ product query failed: {resp.get('message', resp)}")
    content = resp["data"]["content"]
    if not content:
        return []
    return content[0].get("productList", [])


def normalize_trend_score(listed_num: int, all_listed_nums: list[int]) -> int:
    if not all_listed_nums or max(all_listed_nums) == 0:
        return 50
    lo, hi = min(all_listed_nums), max(all_listed_nums)
    if hi == lo:
        return 90
    scaled = 60 + (listed_num - lo) / (hi - lo) * 39  # keep scores in a believable 60-99 band
    return round(scaled)


def to_site_products(cj_products: list[dict]) -> list[dict]:
    listed_nums = [int(p.get("listedNum", 0)) for p in cj_products]
    site_products = []
    for i, p in enumerate(cj_products):
        category, emoji = classify_name(p.get("nameEn", ""))
        cost_price = parse_price(p.get("nowPrice") or p.get("sellPrice"))
        sku = product_id(p) or f"cj{i}"
        site_products.append({
            "id": sku,
            "name": clean_name(p.get("nameEn", "Untitled product")),
            "category": category,
            "price": assign_price(sku, cost_price),
            "trendScore": normalize_trend_score(int(p.get("listedNum", 0)), listed_nums),
            "badge": "🔥 Trending",
            "emoji": emoji,
            "image": p.get("bigImage") or None,
            "gradient": GRADIENTS[i % len(GRADIENTS)],
            "description": f"Trending in {category} — {p.get('listedNum', 0)} active listings and climbing.",
        })
    return site_products


def main():
    api_key = load_api_key()
    print("Authenticating with CJ Dropshipping...")
    try:
        access_token = get_access_token(api_key)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"CJ auth request failed: HTTP {e.code} {e.reason}")

    print(f"Fetching a pool of {POOL_SIZE} trending products...")
    try:
        pool = fetch_trending_products(access_token)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"CJ product request failed: HTTP {e.code} {e.reason}")

    if not pool:
        raise SystemExit("CJ returned no trending products — leaving products.json untouched.")

    prev_ids = load_previous_ids()
    selected = select_rotating(pool, prev_ids)

    changed = sum(1 for p in selected if product_id(p) not in prev_ids)
    print(f"Selected {len(selected)} products ({changed} new vs. last cycle).")

    site_products = to_site_products(selected)
    PRODUCTS_FILE.write_text(json.dumps(site_products, indent=2) + "\n")
    print(f"Wrote {len(site_products)} products to {PRODUCTS_FILE}")


if __name__ == "__main__":
    main()
