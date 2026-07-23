"""
Generates fresh, paste-ready social posts (Twitter/X, Facebook, TikTok) from the
current products.json. Runs automatically after each catalog refresh so there's
always current post copy waiting.

Usage:
    python generate_posts.py   ->  writes marketing/latest-posts.md
"""

import json
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent
PRODUCTS_FILE = HERE / "products.json"
OUT_DIR = HERE / "marketing"
OUT_FILE = OUT_DIR / "latest-posts.md"
LINK = "https://matthewferreira818.github.io/hotstuff/"

# Per-category flavor. Falls back to the "*" entry for anything unmapped.
HOOK = {
    "Kitchen": "Your kitchen's about to get an upgrade",
    "Home": "Instant cozy upgrade",
    "Beauty": "Add this to the routine",
    "Fitness": "Level up your setup",
    "Electronics": "The gadget you didn't know you needed",
    "Toys": "Guaranteed to be a hit",
    "Pet": "Your pet's about to be spoiled",
    "Fashion": "The piece people notice",
    "Jewelry": "The piece people ask about",
    "Outdoor": "Adventure-ready",
    "Bags": "Everyday carry, upgraded",
    "Footwear": "Comfort meets trend",
    "Phone Accessories": "Phone essential, unlocked",
    "Tools": "Fix-it just got easier",
    "Sports": "Game-day ready",
    "*": "Trending right now",
}
TAGS = {
    "Kitchen": "#kitchengadgets #tiktokmademebuyit",
    "Home": "#cozyhome #homefinds",
    "Beauty": "#beauty #selfcare",
    "Fitness": "#fitness #homegym",
    "Electronics": "#gadgets #techtok",
    "Toys": "#giftideas #tiktokmademebuyit",
    "Pet": "#petsofx #dogsofx",
    "Fashion": "#fashion #ootd",
    "Jewelry": "#jewelry #giftideas",
    "Outdoor": "#outdoors #adventure",
    "Bags": "#everydaycarry #style",
    "Footwear": "#shoes #comfort",
    "Phone Accessories": "#gadgets #phoneaccessories",
    "Tools": "#tools #diy",
    "Sports": "#sports #fitness",
    "*": "#trending #tiktokmademebuyit",
}
FB_LINE = {
    "Kitchen": "One of those little kitchen upgrades you didn't know you needed until you had it.",
    "Home": "The kind of small thing that instantly makes a room feel cozier.",
    "Beauty": "A simple add to the routine that just makes life a little nicer.",
    "Fitness": "Perfect for squeezing a little more into your day without the gym.",
    "Electronics": "A tiny gadget that quietly solves an everyday annoyance.",
    "Pet": "Your dog or cat is about to claim this as their favorite thing.",
    "Fashion": "Simple, versatile, and the kind of thing that gets noticed.",
    "Jewelry": "Simple and sweet — the kind of piece people actually ask about.",
    "Sports": "Built for the people who'd rather be moving than sitting still.",
    "*": "One of this week's trending finds — here before it rotates out.",
}
TT_CONCEPT = {
    "Kitchen": "Quick demo: show it in action solving a real kitchen moment in one 8-sec shot. Trending sound.",
    "Home": "Lights-on → lights-off reveal. The transformation is the hook.",
    "Beauty": "Before/after or a satisfying close-up. Keep it clean and bright.",
    "Fitness": "Casual 'using it while watching TV' clip. Relatable > polished.",
    "Electronics": "'POV: [the problem]' → show the gadget solving it. Mini-story.",
    "Pet": "Put it down, cut to your pet already loving it. Cute wins.",
    "Fashion": "Quick try-on or styling clip with a trending sound.",
    "Jewelry": "Daylight → close-up reveal of the detail/sparkle. The reveal is the video.",
    "Sports": "Fast action clip of it in use. Energy + trending sound.",
    "*": "Show the product doing its one cool thing in the first 2 seconds. Trending sound.",
}


def flavor(table, category):
    return table.get(category, table["*"])


def price(p):
    return f"${float(p['price']):.2f}"


def twitter_post(p):
    return (
        f"{flavor(HOOK, p['category'])} {p.get('emoji', '')}\n"
        f"{p['name']} — just {price(p)} at HotsTuff 🔥\n"
        f"[LINK] {flavor(TAGS, p['category'])}"
    )


def facebook_post(p):
    return (
        f"{p.get('emoji', '')} {p['name']} — {price(p)}\n\n"
        f"{flavor(FB_LINE, p['category'])}\n\n"
        f"Grab one before it rotates out 👇\n[LINK]"
    )


def tiktok_post(p):
    caption_tags = flavor(TAGS, p["category"]).replace("#tiktokmademebuyit", "").strip()
    return (
        f"🎬 Concept: {flavor(TT_CONCEPT, p['category'])}\n"
        f"📝 Caption: {p['name'].lower()} for {price(p)} — link in bio "
        f"#tiktokmademebuyit {caption_tags}"
    )


def build():
    products = json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))
    ranked = sorted(products, key=lambda x: x.get("trendScore", 0), reverse=True)
    heroes = ranked[:5]  # top items get the fuller Facebook + TikTok treatment

    lines = []
    lines.append("# HotsTuff — This Cycle's Posts (auto-generated)\n")
    lines.append(
        f"_Generated {date.today().isoformat()} from the current lineup "
        f"({len(products)} products). Replace `[LINK]` with_ **{LINK}**\n"
    )
    lines.append(
        "> Post these over the next ~3 days (until the catalog rotates again and "
        "this file updates). Mix platforms, stagger times, reply to comments. "
        "Never promise fast shipping — it's ~1–3 weeks.\n"
    )

    lines.append("\n---\n\n## 🐦 Twitter/X — one per product\n")
    for p in ranked:
        lines.append(f"> {twitter_post(p)}\n")

    lines.append("\n---\n\n## 📘 Facebook — top picks (attach the product photo)\n")
    for p in heroes:
        lines.append(f"**{p['name']} — {price(p)}**\n")
        lines.append("```\n" + facebook_post(p) + "\n```\n")

    lines.append("\n---\n\n## 🎵 TikTok — top picks (film on your phone)\n")
    for p in heroes:
        lines.append(f"**{p['name']} — {price(p)}**\n")
        lines.append(tiktok_post(p) + "\n")

    lines.append(
        "\n---\n\n_Auto-generated by `generate_posts.py` on each catalog refresh. "
        "For the full evergreen playbook (profile setup, engagement posts, reply "
        "templates, calendar), see `HotsTuff-ads/ad-kit.md` and "
        "`HotsTuff-ads/platform-posts.md`._\n"
    )

    OUT_DIR.mkdir(exist_ok=True)
    OUT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_FILE} ({len(products)} products, {len(heroes)} heroes).")


if __name__ == "__main__":
    build()
