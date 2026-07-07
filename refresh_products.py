"""
Pulls currently-trending products from CJ Dropshipping and rewrites products.json.

Usage:
    python refresh_products.py

Requires a .env file (same folder) containing:
    CJ_API_KEY=CJUserNum@api@xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
"""

import json
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

PRODUCT_COUNT = 8
MARKUP_MULTIPLIER = 1.6  # sell price = supplier cost * markup

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


MAX_NAME_LENGTH = 55


def clean_name(name: str) -> str:
    name = " ".join((name or "").split())  # collapse whitespace
    if len(name) <= MAX_NAME_LENGTH:
        return name
    truncated = name[:MAX_NAME_LENGTH].rsplit(" ", 1)[0]
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
        "size": PRODUCT_COUNT,
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
        site_products.append({
            "id": p.get("sku") or p.get("id") or f"cj{i}",
            "name": clean_name(p.get("nameEn", "Untitled product")),
            "category": category,
            "price": round(cost_price * MARKUP_MULTIPLIER, 2),
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

    print(f"Fetching top {PRODUCT_COUNT} trending products...")
    try:
        cj_products = fetch_trending_products(access_token)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"CJ product request failed: HTTP {e.code} {e.reason}")

    if not cj_products:
        raise SystemExit("CJ returned no trending products — leaving products.json untouched.")

    site_products = to_site_products(cj_products)
    PRODUCTS_FILE.write_text(json.dumps(site_products, indent=2) + "\n")
    print(f"Wrote {len(site_products)} products to {PRODUCTS_FILE}")


if __name__ == "__main__":
    main()
