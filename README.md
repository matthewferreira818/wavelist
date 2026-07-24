# HotsTuff

A landing page for a storefront whose catalog changes based on what's currently
trending — not a single fixed product.

**Live site:** https://findhotstuff.com/
**Repo:** https://github.com/matthewferreira818/hotstuff

Note: the checkout backend (Cloudflare Worker) keeps its internal name
`wavelist-checkout` — that's backend plumbing, not customer-facing, so it
wasn't renamed to avoid re-registering the live Stripe webhook.

## Running locally

Any static file server works, e.g.:

```
npx serve .
```

Then open the printed local URL. `index.html` fetches `products.json`, so the
page must be served over http(s) — opening `index.html` directly via
`file://` will block the fetch in most browsers.

## Automatic trending refresh

`products.json` is regenerated every 3 days at 09:00 UTC by a GitHub Actions
workflow ([`.github/workflows/refresh-products.yml`](.github/workflows/refresh-products.yml))
that runs `refresh_products.py` against the CJ Dropshipping API, commits the
result if it changed, and pushes — which triggers GitHub Pages to redeploy
automatically. This runs in the cloud, independent of whether your machine
is on. (The cron `0 9 */3 * *` fires on days 1, 4, 7 … 28, 31 of each month,
so the interval around a month boundary is a little shorter than 3 days.)

The site shows **13 products** each cycle (`DISPLAY_COUNT`), selected from a
pool of the top **60** trending items (`POOL_SIZE`). At most `MAX_REPEATS` (3)
items carry over from the previous cycle, so **at least 10 of the 13 change
every cycle** — the carried-over items are the hottest repeats, for a bit of
continuity.

- **Trigger it manually:** GitHub repo → Actions tab → "Refresh trending
  products" → Run workflow. Or: `gh workflow run refresh-products.yml`.
- **The API key** is stored as a GitHub Actions secret (`CJ_API_KEY`), not in
  the repo. To rotate it: `gh secret set CJ_API_KEY --repo matthewferreira818/hotstuff`.

To run the refresh manually on your own machine instead:

```
python refresh_products.py
```

Requires a `.env` file (not committed — see `.gitignore`) containing:

```
CJ_API_KEY=CJUserNum@api@xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**Known limitations of the auto-refresh:**
- Each product is assigned a stable retail price from `PRICE_LADDER`
  (a spread of points across ~$4–$25), chosen deterministically from its SKU
  so its price stays the same across cycles. The price is then raised if
  needed so it never drops below the supplier cost marked up by
  `MARKUP_MULTIPLIER` (1.6x) — this protects margin. Because the ladder is
  seeded by SKU, the exact prices on the site depend on which items are
  trending. Edit `PRICE_LADDER` / `MARKUP_MULTIPLIER` to change the range.
- Category and emoji are guessed from keywords in the product title (CJ's
  list endpoint doesn't return category names), so occasionally a product
  lands in the generic "Trending Finds" bucket — check `NAME_KEYWORD_CATEGORIES`
  in `refresh_products.py` to add more keyword mappings.
- Product titles are supplier SEO titles, truncated to 55 characters — not
  copywritten.
- Product photos come straight from CJ's `bigImage` field; if a URL 404s the
  card silently falls back to the emoji treatment (see `script.js`).

## Managing content manually (add / delete products)

All catalog content lives in [`products.json`](products.json). You can also
edit this file directly any time — the next scheduled refresh will overwrite
manual edits, so for permanent manual entries, disable the Actions workflow
or accept the change won't survive the next Monday refresh.

Each entry looks like:

```json
{
  "id": "p7",
  "name": "Product Name",
  "category": "Category",
  "price": 24.99,
  "trendScore": 85,
  "badge": "🔥 Trending",
  "emoji": "🎧",
  "image": "https://example.com/product.jpg",
  "gradient": "linear-gradient(135deg, #6366f1, #ec4899)",
  "description": "One sentence on why it's trending."
}
```

- **Add a product**: append a new object to the array in `products.json`
  with a unique `id`.
- **Remove a product**: delete its object from the array.
- **Reorder**: not needed — the page always sorts by `trendScore`
  (highest first) automatically.
- `badge` is free text shown as a pill on the card (e.g. `"New"`,
  `"Best Seller"`, `"🔥 Trending"`).
- `image` is optional — omit it (or set to `null`) to fall back to the
  `emoji` + `gradient` thumbnail.
- `gradient` is any valid CSS `background` value for the card's thumbnail.

No build step or restart is required — the page re-fetches `products.json`
on every load.

## Checkout / payments (live)

Each product card has a "Buy now" button that:
1. Calls the `checkout-worker` (Cloudflare Worker, deployed at
   https://wavelist-checkout.wavelist-mf818.workers.dev) with the product id.
2. The Worker looks the product up in the live `products.json` (never trusts
   client-supplied price), creates a **live** Stripe Checkout Session, and
   returns the redirect URL.
3. Customer pays on Stripe's hosted checkout page (card + shipping address).
4. Stripe sends a `checkout.session.completed` webhook back to the Worker,
   which verifies the signature and places the matching order with CJ
   Dropshipping (`payType=2`, auto-deducted from your CJ account balance) so
   it actually ships.

**This uses real Stripe live-mode payments — real money moves.**

### Required before taking real sales
- **Your CJ Dropshipping account balance must be funded.** Order fulfillment
  auto-deducts the wholesale cost from your CJ balance on every sale
  (`payType=2` in `checkout-worker/src/index.js`). If the balance is
  insufficient, Stripe will have collected the customer's payment but CJ
  will **not** ship the item — fund this before announcing the store.

### Worker project layout
- `checkout-worker/src/index.js` — both endpoints (`/create-checkout-session`,
  `/webhook`)
- `checkout-worker/wrangler.toml` — Worker config + KV namespace binding
  (`ORDERS_KV`, used to make webhook processing idempotent against Stripe's
  retries)
- Secrets (`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `CJ_API_KEY`) live in
  Cloudflare, not in this repo. To rotate:
  ```
  cd checkout-worker
  npx wrangler secret put STRIPE_SECRET_KEY
  npx wrangler secret put STRIPE_WEBHOOK_SECRET
  npx wrangler secret put CJ_API_KEY
  npx wrangler deploy
  ```
- To check a specific order's fulfillment result: it's stored in the
  `ORDERS_KV` namespace keyed by the Stripe Checkout Session id
  (`npx wrangler kv key get <session_id> --binding ORDERS_KV --remote`).

### Known limitations
- Only ships to the US (`shipping_address_collection` in the Worker).
- No inventory/stock check against CJ before accepting payment — if a
  product goes out of stock at CJ between page load and purchase, the CJ
  order call will fail (logged in `ORDERS_KV`, not currently surfaced back
  to the customer or you — check KV or Worker logs periodically for now).
- No refund automation — refunds are manual via the Stripe dashboard.
