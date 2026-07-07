# Wavelist

A landing page for a storefront whose catalog changes based on what's currently
trending — not a single fixed product.

**Live site:** https://matthewferreira818.github.io/wavelist/
**Repo:** https://github.com/matthewferreira818/wavelist

## Running locally

Any static file server works, e.g.:

```
npx serve .
```

Then open the printed local URL. `index.html` fetches `products.json`, so the
page must be served over http(s) — opening `index.html` directly via
`file://` will block the fetch in most browsers.

## Automatic trending refresh

`products.json` is regenerated every Monday 09:00 UTC by a GitHub Actions
workflow ([`.github/workflows/refresh-products.yml`](.github/workflows/refresh-products.yml))
that runs `refresh_products.py` against the CJ Dropshipping API, commits the
result if it changed, and pushes — which triggers GitHub Pages to redeploy
automatically. This runs in the cloud, independent of whether your machine
is on.

- **Trigger it manually:** GitHub repo → Actions tab → "Refresh trending
  products" → Run workflow. Or: `gh workflow run refresh-products.yml`.
- **The API key** is stored as a GitHub Actions secret (`CJ_API_KEY`), not in
  the repo. To rotate it: `gh secret set CJ_API_KEY --repo matthewferreira818/wavelist`.

To run the refresh manually on your own machine instead:

```
python refresh_products.py
```

Requires a `.env` file (not committed — see `.gitignore`) containing:

```
CJ_API_KEY=CJUserNum@api@xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**Known limitations of the auto-refresh:**
- Prices are the *lowest* variant cost from CJ's price range, marked up by
  `MARKUP_MULTIPLIER` (1.6x) in `refresh_products.py` — real per-variant
  pricing will vary, adjust the multiplier as needed.
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

## Checkout / payments

Not implemented yet. The site is a browsable catalog only — there's no cart
or way to actually buy anything. See the project notes for what's needed to
add real checkout (Stripe account + serverless function + CJ order API).
