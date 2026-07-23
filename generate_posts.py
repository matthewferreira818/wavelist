"""
Generates fresh, paste-ready social posts (Twitter/X, Facebook, TikTok) from the
current products.json. Runs automatically after each catalog refresh so there's
always current post copy waiting.

Tone: upbeat-but-clean on Twitter/Facebook, fun-and-casual on TikTok.

Usage:
    python generate_posts.py   ->  writes marketing/latest-posts.md
"""

import hashlib
import json
import re
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent
PRODUCTS_FILE = HERE / "products.json"
OUT_DIR = HERE / "marketing"
OUT_FILE = OUT_DIR / "latest-posts.md"
LINK = "https://hotstufffinds.com/"


def pick(options, sku):
    """Stable-but-varied choice from a list, seeded by the product SKU."""
    h = int(hashlib.sha256((sku or "x").encode()).hexdigest(), 16)
    return options[h % len(options)]


# --- Clean short "ad names" ------------------------------------------------
# Raw supplier titles are long and get truncated with "…". For ad copy we want
# a punchy short name. Keyword match first (great names for common trending
# types); fall back to the first few words of the title if nothing matches.
AD_NAMES = [
    (("humidifier",), "Projector Humidifier"),
    (("juicer", "blender"), "Portable USB Blender"),
    (("protein", "shaker", "stirrer"), "Electric Protein Shaker"),
    (("finder", "tracker", "anti lost", "anti-lost"), "Bluetooth Item Finder"),
    (("trainer", "grip"), "Grip & Forearm Trainer"),
    (("seat belt", "seat vehicle", "car seat"), "Pet Car Seat Belt"),
    (("hair remover", "lint"), "Reusable Pet Hair Remover"),
    (("phone holder", "car mount", "dashboard"), "Telescopic Car Phone Mount"),
    (("gloves",), "Touchscreen Winter Gloves"),
    (("jacket",), "Fleece Winter Jacket"),
    (("bed",), "Cozy 2-in-1 Pet Bed"),
    (("humidifier",), "Projector Humidifier"),
]


def ad_name(raw: str, category: str) -> str:
    low = (raw or "").lower()
    # necklaces get a descriptor-aware name
    if "necklace" in low or "pendant" in low:
        if "moon" in low:
            return "Glowing Moon Necklace"
        if any(w in low for w in ("couple", "hug", "love")):
            return "Couple's Hug Necklace"
        return "Statement Necklace"
    for keywords, label in AD_NAMES:
        if any(k in low for k in keywords):
            return label
    # fallback: first 4 meaningful words, no trailing ellipsis / spec noise
    words = re.sub(r"[…]", "", raw or "").split()
    words = [w for w in words if not re.fullmatch(r"\d+(ml|g|cm|mm|pcs)?", w.lower())]
    short = " ".join(words[:4]).strip()
    return short or (raw or "Trending Find")


# --- Tone / flavor tables --------------------------------------------------
HOOKS = {
    "Kitchen": ["Your kitchen just got an upgrade", "The kitchen gadget everyone's grabbing", "Small upgrade, big difference"],
    "Home": ["Instant cozy upgrade", "Your space is about to feel so much better", "The coziest thing you'll buy this week"],
    "Beauty": ["Add this to the routine", "A little self-care upgrade", "The easy glow-up"],
    "Fitness": ["Level up your setup", "Progress from your living room", "The easy win for your routine"],
    "Electronics": ["The gadget you didn't know you needed", "Tiny gadget, huge difference", "It solves such an annoying problem"],
    "Toys": ["Guaranteed to be a hit", "The gift that always lands", "Instant fun unlocked"],
    "Pet": ["Your pet's about to be spoiled", "Your dog or cat will thank you", "Pet-parent essential"],
    "Fashion": ["The piece people notice", "Effortless and on-trend", "Your new go-to"],
    "Jewelry": ["The piece people ask about", "Simple, sweet, and it stands out", "A gift that actually lands"],
    "Sports": ["Game-day ready", "Built for the outdoors", "Gear up"],
    "*": ["Trending right now", "This week's must-have", "Everyone's grabbing this"],
}
TAGS = {
    "Kitchen": "#kitchengadgets #tiktokmademebuyit",
    "Home": "#cozyhome #homefinds",
    "Beauty": "#beauty #selfcare",
    "Fitness": "#fitness #homegym",
    "Electronics": "#gadgets #techtok",
    "Pet": "#petsofx #dogsofx",
    "Fashion": "#fashion #ootd",
    "Jewelry": "#jewelry #giftideas",
    "Sports": "#sports #fitness",
    "*": "#trending #tiktokmademebuyit",
}
FB_LINES = {
    "Kitchen": ["One of those little kitchen upgrades you didn't know you needed until you had it.", "Makes an everyday task genuinely nicer — and it's a fun one to gift."],
    "Home": ["The kind of small thing that instantly makes a room feel cozier.", "A tiny touch that changes the whole vibe of a space."],
    "Electronics": ["A tiny gadget that quietly solves an everyday annoyance.", "The kind of thing you'll wonder how you lived without."],
    "Pet": ["Your dog or cat is about to claim this as their favorite thing.", "Because our pets deserve to be a little spoiled."],
    "Fashion": ["Simple, versatile, and the kind of thing that gets noticed.", "Easy to wear, easy to love."],
    "Jewelry": ["Simple and sweet — the kind of piece people actually ask about.", "A thoughtful little gift that doesn't break the bank."],
    "Fitness": ["Perfect for squeezing a little more into your day without the gym.", "Small, simple, and it actually gets used."],
    "Sports": ["Built for the people who'd rather be moving than sitting still.", "Ready when you are."],
    "*": ["One of this week's trending finds — here before it rotates out.", "Fresh in this week and moving fast."],
}
# TikTok = fun & casual (lowercase, playful). {p} = price.
TT_CAPTIONS = {
    "Kitchen": "ok this is actually genius 🥤 only {p} #tiktokmademebuyit #kitchengadgets",
    "Home": "turning my room into a whole vibe for {p} 🌙 #tiktokmademebuyit #cozy",
    "Beauty": "adding this to my routine immediately {p} ✨ #tiktokmademebuyit #beautytok",
    "Fitness": "building strength from my couch ngl 💪 {p} #tiktokmademebuyit #fittok",
    "Electronics": "why did nobody tell me about this 🤯 {p} #tiktokmademebuyit #gadgets",
    "Pet": "she claimed it in 4 seconds fr 🐾 {p} #petsoftiktok #tiktokmademebuyit",
    "Fashion": "the fit is fitting 🔥 {p} #tiktokmademebuyit #fashiontok",
    "Jewelry": "wait it GLOWS?? 🌙✨ {p} #tiktokmademebuyit #jewelrytok",
    "Sports": "needed this one fr {p} 🙌 #tiktokmademebuyit",
    "*": "ok i actually need this 👀 {p} #tiktokmademebuyit #trending",
}
TT_CONCEPT = {
    "Kitchen": "Quick demo — show it working in one 8-sec shot. Trending sound.",
    "Home": "Lights-on → lights-off reveal. The transformation is the hook.",
    "Beauty": "Satisfying close-up or a quick before/after. Keep it bright.",
    "Fitness": "Casual 'using it while watching TV' clip. Relatable > polished.",
    "Electronics": "'POV: [the problem]' → show the gadget solving it. Mini-story.",
    "Pet": "Put it down, cut to your pet already loving it. Cute wins.",
    "Fashion": "Quick try-on / styling clip with a trending sound.",
    "Jewelry": "Daylight → close-up reveal of the sparkle/glow. The reveal IS the video.",
    "Sports": "Fast action clip of it in use. Energy + trending sound.",
    "*": "Show the product doing its one cool thing in the first 2 seconds.",
}


def flavor(table, category):
    return table.get(category, table["*"])


def price(p):
    return f"${float(p['price']):.2f}"


def twitter_post(p, name):  # upbeat + clean
    hook = pick(flavor(HOOKS, p["category"]), p["id"])
    return (
        f"{hook} {p.get('emoji', '')}\n"
        f"{name} — just {price(p)} at HotsTuff 🔥\n"
        f"[LINK] {flavor(TAGS, p['category'])}"
    )


def facebook_post(p, name):  # upbeat + clean, warmer
    line = pick(flavor(FB_LINES, p["category"]), p["id"])
    return (
        f"{p.get('emoji', '')} {name} — {price(p)}\n\n"
        f"{line}\n\n"
        f"Grab one before it rotates out 👇\n[LINK]"
    )


def tiktok_post(p, name):  # fun + casual
    caption = flavor(TT_CAPTIONS, p["category"]).format(p=price(p))
    return f"🎬 Concept: {flavor(TT_CONCEPT, p['category'])}\n📝 Caption: {caption}"


def build():
    products = json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))
    ranked = sorted(products, key=lambda x: x.get("trendScore", 0), reverse=True)
    for p in ranked:
        p["_ad"] = ad_name(p.get("name", ""), p.get("category", ""))
    heroes = ranked[:5]

    L = []
    L.append("# HotsTuff — This Cycle's Posts (auto-generated)\n")
    L.append(
        f"_Generated {date.today().isoformat()} from the current lineup "
        f"({len(products)} products). Replace `[LINK]` with_ **{LINK}**\n"
    )
    L.append(
        "> Tone: upbeat + clean on Twitter/Facebook, fun + casual on TikTok. "
        "Post these over the next ~3 days (until the catalog rotates and this "
        "file updates). Stagger times, reply to comments. Shipping is ~1–3 weeks "
        "— never promise faster.\n"
    )

    L.append("\n---\n\n## 🐦 Twitter/X — one per product\n")
    for p in ranked:
        L.append(f"> {twitter_post(p, p['_ad'])}\n")

    L.append("\n---\n\n## 📘 Facebook — top picks (attach the product photo)\n")
    for p in heroes:
        L.append(f"**{p['_ad']} — {price(p)}**\n")
        L.append("```\n" + facebook_post(p, p["_ad"]) + "\n```\n")

    L.append("\n---\n\n## 🎵 TikTok — top picks (film on your phone)\n")
    for p in heroes:
        L.append(f"**{p['_ad']} — {price(p)}**\n")
        L.append(tiktok_post(p, p["_ad"]) + "\n")

    L.append(
        "\n---\n\n_Auto-generated by `generate_posts.py` on each catalog refresh. "
        "For the evergreen playbook (profile setup, engagement posts, reply "
        "templates, calendar), see `HotsTuff-ads/ad-kit.md` and "
        "`HotsTuff-ads/platform-posts.md`._\n"
    )

    OUT_DIR.mkdir(exist_ok=True)
    OUT_FILE.write_text("\n".join(L), encoding="utf-8")
    print(f"Wrote {OUT_FILE} ({len(products)} products, {len(heroes)} heroes).")


if __name__ == "__main__":
    build()
