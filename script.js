const CHECKOUT_API = "https://wavelist-checkout.wavelist-mf818.workers.dev";

async function loadProducts() {
  const grid = document.getElementById("product-grid");
  const countEl = document.getElementById("product-count");

  grid.innerHTML = "";
  grid.appendChild(emptyState("Loading trending products…"));

  let products;
  try {
    const res = await fetch("products.json", { cache: "no-store" });
    if (!res.ok) throw new Error(`products.json responded with ${res.status}`);
    const data = await res.json();
    if (!Array.isArray(data)) throw new Error("products.json must be an array");
    products = data;
  } catch (err) {
    console.error(err);
    grid.innerHTML = "";
    grid.appendChild(emptyState("Couldn't load the catalog. Is products.json reachable?"));
    countEl.textContent = "0";
    return;
  }

  countEl.textContent = products.length;

  grid.innerHTML = "";

  if (products.length === 0) {
    grid.appendChild(emptyState("No trending products right now — check back soon."));
    return;
  }

  const sorted = [...products].sort(
    (a, b) => (Number(b.trendScore) || 0) - (Number(a.trendScore) || 0)
  );
  for (const product of sorted) {
    grid.appendChild(buildCard(product));
  }
}

function emptyState(message) {
  const div = document.createElement("div");
  div.className = "empty-state";
  div.textContent = message;
  return div;
}

function buildCard(p) {
  const price = (Number(p.price) || 0).toFixed(2);
  const trendScore = Number.isFinite(Number(p.trendScore)) ? p.trendScore : "—";

  const card = document.createElement("article");
  card.className = "card";

  const thumb = document.createElement("div");
  thumb.className = "card-thumb";
  if (typeof p.gradient === "string") {
    thumb.style.background = p.gradient;
  }

  if (typeof p.image === "string" && p.image) {
    const img = document.createElement("img");
    img.className = "card-thumb-img";
    img.src = p.image;
    img.alt = p.name || "";
    img.loading = "lazy";
    img.addEventListener("error", () => img.remove(), { once: true });
    thumb.appendChild(img);
  } else {
    const emojiSpan = document.createElement("span");
    emojiSpan.textContent = p.emoji || "";
    emojiSpan.setAttribute("aria-hidden", "true");
    thumb.appendChild(emojiSpan);
  }

  const badge = document.createElement("span");
  badge.className = "card-badge";
  badge.textContent = p.badge || "";
  thumb.appendChild(badge);

  const body = document.createElement("div");
  body.className = "card-body";

  const category = document.createElement("div");
  category.className = "card-category";
  category.textContent = p.category || "";

  const name = document.createElement("h3");
  name.className = "card-name";
  name.textContent = p.name || "Untitled product";

  const desc = document.createElement("p");
  desc.className = "card-desc";
  desc.textContent = p.description || "";

  const footer = document.createElement("div");
  footer.className = "card-footer";

  const priceEl = document.createElement("span");
  priceEl.className = "card-price";
  priceEl.textContent = `$${price}`;

  const trendEl = document.createElement("span");
  trendEl.className = "card-trend";
  trendEl.textContent = `Trend score ${trendScore}`;

  footer.append(priceEl, trendEl);

  const buyButton = document.createElement("button");
  buyButton.className = "btn btn-primary card-buy";
  buyButton.type = "button";
  buyButton.textContent = "Buy now";
  buyButton.addEventListener("click", () => startCheckout(p.id, buyButton));

  body.append(category, name, desc, footer, buyButton);
  card.append(thumb, body);

  return card;
}

async function startCheckout(productId, button) {
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "Redirecting…";

  try {
    const res = await fetch(`${CHECKOUT_API}/create-checkout-session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ productId }),
    });
    const data = await res.json();
    if (!res.ok || !data.url) {
      throw new Error(data.error || `Checkout request failed (${res.status})`);
    }
    window.location.href = data.url;
  } catch (err) {
    console.error(err);
    button.disabled = false;
    button.textContent = originalText;
    alert("Couldn't start checkout. Please try again in a moment.");
  }
}

function showOrderStatusBanner() {
  const params = new URLSearchParams(window.location.search);
  const main = document.querySelector("main");
  if (params.get("success") === "1") {
    const banner = document.createElement("div");
    banner.className = "order-banner order-banner-success";
    banner.textContent = "Payment received — thank you! Your order is being placed for fulfillment.";
    main.prepend(banner);
  } else if (params.get("canceled") === "1") {
    const banner = document.createElement("div");
    banner.className = "order-banner order-banner-canceled";
    banner.textContent = "Checkout canceled — no charge was made.";
    main.prepend(banner);
  }
}

document.getElementById("year").textContent = new Date().getFullYear();
showOrderStatusBanner();
loadProducts();
