const SITE_URL = "https://findhotstuff.com";
// Origins allowed to call create-checkout-session (custom domain, www, and the
// legacy github.io URL during the transition).
const ALLOWED_ORIGINS = [
  "https://findhotstuff.com",
  "https://www.findhotstuff.com",
  "https://hotstufffinds.com",
  "https://www.hotstufffinds.com",
  "https://matthewferreira818.github.io",
];
// Catalog fetched from raw.githubusercontent so it keeps working regardless of
// which domain the site itself is served from.
const PRODUCTS_URL = "https://raw.githubusercontent.com/matthewferreira818/hotstuff/master/products.json";
const STRIPE_API = "https://api.stripe.com/v1";
const CJ_AUTH_URL = "https://developers.cjdropshipping.com/api2.0/v1/authentication/getAccessToken";
const CJ_ORDER_URL = "https://developers.cjdropshipping.com/api2.0/v1/shopping/order/createOrderV2";

// Countries Stripe Checkout will collect a shipping address for.
const SHIP_COUNTRIES = [
  "CA", "US", "GB", "AU", "NZ", "IE", "DE", "FR", "ES", "IT", "NL",
  "SE", "NO", "DK", "FI", "BE", "AT", "CH", "PT", "PL", "MX", "JP", "SG", "AE",
];

function corsHeaders(request) {
  const origin = request?.headers?.get("Origin") || "";
  const allowed = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return {
    "Access-Control-Allow-Origin": allowed,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Vary": "Origin",
  };
}

function jsonResponse(obj, status, request) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders(request) },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders(request) });
    }

    if (url.pathname === "/create-checkout-session" && request.method === "POST") {
      return handleCreateCheckoutSession(request, env);
    }

    if (url.pathname === "/webhook" && request.method === "POST") {
      return handleWebhook(request, env);
    }

    if (url.pathname === "/orders" && request.method === "GET") {
      return handleOrdersList(url, env);
    }

    return new Response("Not found", { status: 404 });
  },
};

async function handleCreateCheckoutSession(request, env) {
  try {
    const { productId } = await request.json();
    if (!productId) {
      return jsonResponse({ error: "productId required" }, 400, request);
    }

    const productsRes = await fetch(PRODUCTS_URL, { cf: { cacheTtl: 0 } });
    const products = await productsRes.json();
    const product = products.find((p) => p.id === productId);
    if (!product) {
      return jsonResponse({ error: "product not found" }, 404, request);
    }

    const params = new URLSearchParams();
    params.set("mode", "payment");
    params.set("line_items[0][price_data][currency]", "usd");
    params.set("line_items[0][price_data][product_data][name]", product.name);
    if (product.image) {
      params.set("line_items[0][price_data][product_data][images][0]", product.image);
    }
    params.set("line_items[0][price_data][unit_amount]", String(Math.round(product.price * 100)));
    params.set("line_items[0][quantity]", "1");
    params.set("success_url", `${SITE_URL}/?success=1`);
    params.set("cancel_url", `${SITE_URL}/?canceled=1`);
    SHIP_COUNTRIES.forEach((c, i) =>
      params.set(`shipping_address_collection[allowed_countries][${i}]`, c)
    );
    params.set("metadata[cj_sku]", product.id);
    params.set("metadata[product_name]", product.name);

    const stripeRes = await fetch(`${STRIPE_API}/checkout/sessions`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.STRIPE_SECRET_KEY}`,
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: params.toString(),
    });

    const session = await stripeRes.json();
    if (!stripeRes.ok) {
      return jsonResponse({ error: session.error?.message || "stripe error" }, 502, request);
    }

    return jsonResponse({ url: session.url }, 200, request);
  } catch (err) {
    return jsonResponse({ error: String(err) }, 500, request);
  }
}

async function handleWebhook(request, env) {
  const signature = request.headers.get("Stripe-Signature");
  const payload = await request.text();

  const valid = await verifyStripeSignature(payload, signature, env.STRIPE_WEBHOOK_SECRET);
  if (!valid) {
    return new Response("Invalid signature", { status: 400 });
  }

  const event = JSON.parse(payload);

  if (event.type === "checkout.session.completed") {
    await recordOrder(event.data.object, env);
  }

  return new Response("ok", { status: 200 });
}

async function verifyStripeSignature(payload, signatureHeader, secret) {
  if (!signatureHeader) return false;
  const parts = Object.fromEntries(signatureHeader.split(",").map((kv) => kv.split("=")));
  const timestamp = parts.t;
  const expectedSig = parts.v1;
  if (!timestamp || !expectedSig) return false;

  const signedPayload = `${timestamp}.${payload}`;
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const sigBuffer = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(signedPayload));
  const computedSig = [...new Uint8Array(sigBuffer)].map((b) => b.toString(16).padStart(2, "0")).join("");

  return timingSafeEqual(computedSig, expectedSig);
}

function timingSafeEqual(a, b) {
  if (a.length !== b.length) return false;
  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}

// Pull the shipping address + name from wherever Stripe put them (the field
// moved to collected_information; keep the older fallbacks for safety).
function extractShipping(session) {
  const ci = session.collected_information?.shipping_details;
  const sd = session.shipping_details;
  const cd = session.customer_details;
  return {
    address: ci?.address || sd?.address || cd?.address || null,
    name: ci?.name || sd?.name || cd?.name || "",
  };
}

// Record every paid order into a durable, listable log for fulfillment. We also
// make a best-effort CJ API call, but it usually fails from Cloudflare's shared
// IP (CJ caps API users per IP), so the log — not the CJ call — is the source of
// truth. Fulfillment is done manually from the /orders page until CJ auto-placement
// runs from a stable IP.
async function recordOrder(session, env) {
  const key = `order:${session.id}`;
  if (await env.ORDERS_KV.get(key)) {
    console.log("Skipping already-recorded session", session.id);
    return; // idempotent against Stripe webhook retries
  }

  const { address, name } = extractShipping(session);
  const cd = session.customer_details || {};

  const record = {
    sessionId: session.id,
    createdAt: new Date().toISOString(),
    status: "to-fulfill",
    product: {
      sku: session.metadata?.cj_sku || "",
      name: session.metadata?.product_name || "",
      qty: 1,
    },
    amount: (session.amount_total || 0) / 100,
    currency: (session.currency || "usd").toUpperCase(),
    customer: { name: name || cd.name || "", email: cd.email || "", phone: cd.phone || "" },
    ship: address
      ? {
          line1: address.line1 || "",
          line2: address.line2 || "",
          city: address.city || "",
          state: address.state || "",
          postal: address.postal_code || "",
          country: address.country || "",
        }
      : null,
    cj: null,
  };

  // Best-effort CJ auto-placement (works only from a stable/whitelisted IP).
  try {
    if (record.product.sku && address) {
      const tokenRes = await fetch(CJ_AUTH_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ apiKey: env.CJ_API_KEY }),
      });
      const accessToken = (await tokenRes.json())?.data?.accessToken;
      if (accessToken) {
        const orderRes = await fetch(CJ_ORDER_URL, {
          method: "POST",
          headers: { "CJ-Access-Token": accessToken, "Content-Type": "application/json" },
          body: JSON.stringify({
            orderNumber: session.id,
            shippingCustomerName: record.customer.name || "Customer",
            shippingAddress: address.line1 || "",
            shippingAddress2: address.line2 || "",
            shippingCity: address.city || "",
            shippingProvince: address.state || "",
            shippingZip: address.postal_code || "",
            shippingCountryCode: address.country || "US",
            shippingPhone: record.customer.phone || "",
            payType: 1,
            products: [{ sku: record.product.sku, quantity: 1 }],
          }),
        });
        const od = await orderRes.json();
        if (od?.result) {
          record.status = "auto-placed";
          record.cj = { orderId: od.data?.orderId || "", payUrl: od.data?.cjPayUrl || "" };
        } else {
          record.cj = { error: od?.message || "unknown" };
        }
      } else {
        record.cj = { error: "cj-auth-failed" };
      }
    }
  } catch (err) {
    record.cj = { error: String(err) };
  }

  await env.ORDERS_KV.put(key, JSON.stringify(record));
  console.log("Recorded order", session.id, "status", record.status);
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

// Private orders page: GET /orders?token=<ORDERS_ADMIN_TOKEN>
async function handleOrdersList(url, env) {
  const token = url.searchParams.get("token") || "";
  if (!env.ORDERS_ADMIN_TOKEN || token !== env.ORDERS_ADMIN_TOKEN) {
    return new Response("Unauthorized", { status: 401 });
  }

  const list = await env.ORDERS_KV.list({ prefix: "order:" });
  const orders = [];
  for (const k of list.keys) {
    const v = await env.ORDERS_KV.get(k.name);
    if (v) {
      try {
        orders.push(JSON.parse(v));
      } catch {
        /* skip malformed */
      }
    }
  }
  orders.sort((a, b) => (b.createdAt || "").localeCompare(a.createdAt || ""));

  const rows = orders
    .map((o) => {
      const s = o.ship || {};
      const addr = o.ship
        ? [s.line1, s.line2, `${s.city}, ${s.state} ${s.postal}`, s.country]
            .filter(Boolean)
            .map(escapeHtml)
            .join("<br>")
        : '<span style="color:#b91c1c">no address</span>';
      const cjNote = o.cj?.error
        ? `<span style="color:#b91c1c">auto-place failed: ${escapeHtml(o.cj.error)}</span>`
        : o.cj?.orderId
        ? `CJ #${escapeHtml(o.cj.orderId)}`
        : "—";
      return `<tr>
        <td>${escapeHtml((o.createdAt || "").slice(0, 16).replace("T", " "))}</td>
        <td><span class="status ${escapeHtml(o.status)}">${escapeHtml(o.status)}</span></td>
        <td><b>${escapeHtml(o.product?.name || o.product?.sku)}</b><br><small>SKU ${escapeHtml(o.product?.sku)} &times;${o.product?.qty || 1}</small></td>
        <td>$${escapeHtml(o.amount)} ${escapeHtml(o.currency)}</td>
        <td>${escapeHtml(o.customer?.name)}<br><small>${escapeHtml(o.customer?.email)}<br>${escapeHtml(o.customer?.phone)}</small></td>
        <td>${addr}</td>
        <td>${cjNote}</td>
      </tr>`;
    })
    .join("");

  const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>HotsTuff Orders</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#fff9f2;color:#2a1a2e;}
  header{padding:18px 24px;border-bottom:1px solid #eadfd5;}
  h1{margin:0;font-size:20px;} .sub{color:#7a6a72;font-size:13px;margin-top:4px;}
  .wrap{overflow-x:auto;padding:16px 24px;}
  table{border-collapse:collapse;width:100%;min-width:820px;font-size:13px;}
  th,td{text-align:left;padding:10px 12px;border-bottom:1px solid #eadfd5;vertical-align:top;}
  th{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:#7a6a72;}
  small{color:#7a6a72;}
  .status{font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px;}
  .status.to-fulfill{background:#fee2e2;color:#b91c1c;}
  .status.auto-placed{background:#dcfce7;color:#15803d;}
  .empty{padding:40px;text-align:center;color:#7a6a72;}
</style></head><body>
<header><h1>HotsTuff — Orders to fulfill</h1>
<div class="sub">${orders.length} order(s). "to-fulfill" = place & pay this order in the CJ dashboard using the shipping address shown.</div></header>
<div class="wrap">${
    orders.length
      ? `<table><thead><tr><th>Date (UTC)</th><th>Status</th><th>Product</th><th>Paid</th><th>Customer</th><th>Ship to</th><th>CJ</th></tr></thead><tbody>${rows}</tbody></table>`
      : '<div class="empty">No orders yet.</div>'
  }</div>
</body></html>`;

  return new Response(html, { status: 200, headers: { "Content-Type": "text/html; charset=utf-8" } });
}
