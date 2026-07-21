const ALLOWED_ORIGIN = "https://matthewferreira818.github.io";
const PRODUCTS_URL = "https://matthewferreira818.github.io/wavelist/products.json";
const STRIPE_API = "https://api.stripe.com/v1";
const CJ_AUTH_URL = "https://developers.cjdropshipping.com/api2.0/v1/authentication/getAccessToken";
const CJ_ORDER_URL = "https://developers.cjdropshipping.com/api2.0/v1/shopping/order/createOrderV2";

function corsHeaders() {
  return {
    "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  };
}

function jsonResponse(obj, status) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders() },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders() });
    }

    if (url.pathname === "/create-checkout-session" && request.method === "POST") {
      return handleCreateCheckoutSession(request, env);
    }

    if (url.pathname === "/webhook" && request.method === "POST") {
      return handleWebhook(request, env);
    }

    return new Response("Not found", { status: 404 });
  },
};

async function handleCreateCheckoutSession(request, env) {
  try {
    const { productId } = await request.json();
    if (!productId) {
      return jsonResponse({ error: "productId required" }, 400);
    }

    const productsRes = await fetch(PRODUCTS_URL, { cf: { cacheTtl: 0 } });
    const products = await productsRes.json();
    const product = products.find((p) => p.id === productId);
    if (!product) {
      return jsonResponse({ error: "product not found" }, 404);
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
    params.set("success_url", "https://matthewferreira818.github.io/wavelist/?success=1");
    params.set("cancel_url", "https://matthewferreira818.github.io/wavelist/?canceled=1");
    params.set("shipping_address_collection[allowed_countries][0]", "US");
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
      return jsonResponse({ error: session.error?.message || "stripe error" }, 502);
    }

    return jsonResponse({ url: session.url }, 200);
  } catch (err) {
    return jsonResponse({ error: String(err) }, 500);
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
    await fulfillOrder(event.data.object, env);
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

async function fulfillOrder(session, env) {
  const alreadyProcessed = await env.ORDERS_KV.get(session.id);
  if (alreadyProcessed) {
    console.log("Skipping already-processed session", session.id);
    return;
  }

  const cjSku = session.metadata?.cj_sku;
  if (!cjSku) {
    console.log("No cj_sku in session metadata", session.id);
    return;
  }

  const address = session.shipping_details?.address || session.customer_details?.address;
  if (!address) {
    console.log("No shipping address on session", session.id);
    await env.ORDERS_KV.put(session.id, "failed:no-address");
    return;
  }

  const tokenRes = await fetch(CJ_AUTH_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ apiKey: env.CJ_API_KEY }),
  });
  const tokenData = await tokenRes.json();
  const accessToken = tokenData?.data?.accessToken;
  if (!accessToken) {
    console.log("CJ auth failed", JSON.stringify(tokenData));
    await env.ORDERS_KV.put(session.id, "failed:cj-auth");
    return;
  }

  const orderBody = {
    orderNumber: session.id,
    shippingCustomerName: session.shipping_details?.name || session.customer_details?.name || "Customer",
    shippingAddress: address.line1 || "",
    shippingAddress2: address.line2 || "",
    shippingCity: address.city || "",
    shippingProvince: address.state || "",
    shippingZip: address.postal_code || "",
    shippingCountryCode: address.country || "US",
    shippingPhone: session.customer_details?.phone || "",
    payType: 2,
    products: [{ sku: cjSku, quantity: 1 }],
  };

  const orderRes = await fetch(CJ_ORDER_URL, {
    method: "POST",
    headers: {
      "CJ-Access-Token": accessToken,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(orderBody),
  });
  const orderData = await orderRes.json();
  console.log("CJ order result", JSON.stringify(orderData));

  await env.ORDERS_KV.put(
    session.id,
    orderData?.result ? `fulfilled:${orderData.data?.orderId}` : `failed:${orderData?.message || "unknown"}`
  );
}
