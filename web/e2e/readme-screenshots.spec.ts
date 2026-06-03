/**
 * readme-screenshots.spec.ts
 *
 * Captures the README Screens flow tour to docs/images/.
 * Requires the full stack to be running (./scripts/dev.sh) with a live LLM key.
 *
 * Run: cd web && pnpm exec playwright test e2e/readme-screenshots.spec.ts
 *
 * Output lands in docs/images/ so README image references resolve without a copy step.
 * Chat shots are non-deterministic (LLM); re-run any that render a blank/loading state.
 */

import { test, type Page } from "@playwright/test";
import * as path from "path";

const OUT_DIR = path.resolve(__dirname, "../../docs/images");

const USERS = {
  customer: { email: "alice.johnson@gmail.com", password: "customer123" },
  admin: { email: "admin.demo@gmail.com", password: "admin123" },
  seller: { email: "seller.demo@gmail.com", password: "seller123" },
};

test.use({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 2,
});

test.setTimeout(180_000);

// ---------------------------------------------------------------------------
// Helpers — mirrors portfolio-screenshots.spec.ts conventions
// ---------------------------------------------------------------------------

async function clearSession(page: Page) {
  await page.goto("/login");
  await page.evaluate(() => {
    localStorage.removeItem("ecommerce_user");
    localStorage.removeItem("ecommerce_access_token");
    localStorage.removeItem("ecommerce_refresh_token");
  });
}

async function login(page: Page, email: string, password: string) {
  await clearSession(page);
  await page.goto("/login");
  await page.fill('input[type="email"]', email);
  await page.fill('input[type="password"]', password);
  await page.getByRole("button", { name: /log\s*in|sign\s*in/i }).click();
  await page.waitForURL(/\/chat/, { timeout: 15_000 });
  await page.waitForLoadState("networkidle").catch(() => {});
}

async function shoot(page: Page, filename: string, fullPage = true) {
  await page.waitForTimeout(800);
  await page.screenshot({
    path: path.join(OUT_DIR, filename),
    fullPage,
  });
  console.log(`Saved ${filename}`);
}

async function sendChat(page: Page, message: string, waitMs = 25_000) {
  const input = page.locator("textarea").first();
  await input.waitFor({ state: "visible", timeout: 15_000 });
  await input.click();
  await input.fill(message);
  await input.press("Enter");
  // Wait for the LLM response + SSE steps to land (cards arrive after stream completes)
  await page.waitForTimeout(waitMs);
}

// ---------------------------------------------------------------------------
// Group A — Guest / no-login
// ---------------------------------------------------------------------------

test("guest-01 public storefront", async ({ page }) => {
  await clearSession(page);
  await page.goto("/shop");
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(1_000);
  await shoot(page, "flow-guest-storefront.png", false);
});

test("guest-02 public product grid", async ({ page }) => {
  await clearSession(page);
  await page.goto("/shop/products");
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(1_000);
  await shoot(page, "flow-guest-browse.png");
});

test("guest-03 public product detail", async ({ page }) => {
  await clearSession(page);
  // Fetch the first product id from the public REST endpoint (no auth required)
  await page.goto("/shop/products");
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(1_000);

  // Try clicking the first product card image
  const productImg = page.locator("img[src*='picsum'], img[alt]").first();
  await productImg
    .click({ timeout: 8_000 })
    .catch(async () => {
      // Fallback: resolve via API
      const resp = await page.request.get("http://localhost:8080/api/products?limit=1");
      const data = await resp.json().catch(() => null);
      const id = data?.products?.[0]?.id ?? data?.[0]?.id;
      if (id) await page.goto(`/shop/products/${id}`);
    });

  await page.waitForURL(/\/shop\/products\/[^/]+$/, { timeout: 10_000 }).catch(() => {});
  await page.waitForLoadState("networkidle").catch(() => {});
  await shoot(page, "flow-guest-product.png");
});

test("guest-04 public AI assistant", async ({ page }) => {
  await clearSession(page);
  await page.goto("/shop/assistant");
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(500);
  await sendChat(page, "Show me wireless headphones under $150 — what are my best options?", 28_000);
  await shoot(page, "flow-guest-assistant.png");
});

// ---------------------------------------------------------------------------
// Group B — Authenticated AI shopping flow (chat surface)
// ---------------------------------------------------------------------------

test("flow-01 product search", async ({ page }) => {
  await login(page, USERS.customer.email, USERS.customer.password);
  await page.goto("/chat");
  await page.waitForLoadState("networkidle").catch(() => {});
  await sendChat(page, "Show me wireless headphones under $100", 28_000);
  await shoot(page, "flow-product-search.png");
});

test("flow-02 add to cart", async ({ page }) => {
  await login(page, USERS.customer.email, USERS.customer.password);
  await page.goto("/chat");
  await page.waitForLoadState("networkidle").catch(() => {});
  await sendChat(page, "Recommend a stylish backpack and add the best one to my cart", 28_000);
  await shoot(page, "flow-add-to-cart.png");
});

test("flow-03 view cart", async ({ page }) => {
  await login(page, USERS.customer.email, USERS.customer.password);
  await page.goto("/chat");
  await page.waitForLoadState("networkidle").catch(() => {});
  await sendChat(page, "Show me what's in my cart", 25_000);
  await shoot(page, "flow-view-cart.png");
});

test("flow-04 order tracking", async ({ page }) => {
  await login(page, USERS.customer.email, USERS.customer.password);
  await page.goto("/chat");
  await page.waitForLoadState("networkidle").catch(() => {});
  await sendChat(page, "What's the status of my latest order?", 28_000);
  await shoot(page, "flow-order-tracking.png");
});

test("flow-05 refund / return", async ({ page }) => {
  await login(page, USERS.customer.email, USERS.customer.password);
  await page.goto("/chat");
  await page.waitForLoadState("networkidle").catch(() => {});
  await sendChat(
    page,
    "I want to return my most recent delivered order — what do I need to do?",
    28_000,
  );
  await shoot(page, "flow-refund.png");
});
