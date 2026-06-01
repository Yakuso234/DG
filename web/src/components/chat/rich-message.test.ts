import { describe, expect, it } from "vitest";
import { parseContent, type Segment } from "./rich-message";

const PRODUCT = {
  name: "Sony WH-1000XM5",
  id: "74427b99-8717-4481-8c00-d05dd19b120f",
  price: 299.99,
  original_price: 349.99,
  rating: 4.7,
  review_count: 15,
  category: "Electronics",
  brand: "Sony",
  description: "Premium wireless noise-cancelling headphones.",
};

const PRODUCT_2 = {
  name: "AirPods Max",
  id: "7cf9d9fe-e75a-4e49-b1fb-12bc92d4b1e4",
  price: 449.99,
  rating: 4.5,
  category: "Electronics",
  brand: "Apple",
};

const cardTypes = (segs: Segment[]) => segs.filter((s) => s.type !== "text").map((s) => s.type);
const textOf = (segs: Segment[]) => segs.filter((s) => s.type === "text").map((s) => s.text).join(" ");

describe("parseContent — card fence parsing", () => {
  it("parses a clean fenced product block with newline", () => {
    const content = "Here's a pick:\n```product\n" + JSON.stringify(PRODUCT) + "\n```\nWant more?";
    const segs = parseContent(content);
    expect(cardTypes(segs)).toEqual(["product"]);
    const card = segs.find((s) => s.type === "product");
    expect(card?.data?.name).toBe("Sony WH-1000XM5");
  });

  it("parses a COLLAPSED fence where the transport dropped the newline", () => {
    // ```product{...}``` — no newline after the marker (the real bug)
    const content = "See details below:```product" + JSON.stringify(PRODUCT) + "```Would you like more?";
    const segs = parseContent(content);
    expect(cardTypes(segs)).toEqual(["product"]);
    // The raw JSON must NOT leak into a text segment
    expect(textOf(segs)).not.toContain('"id"');
    expect(textOf(segs)).not.toContain("product{");
  });

  it("dedupes the same product when it arrives both clean and collapsed", () => {
    const content =
      "Take a look:```product" + JSON.stringify(PRODUCT) + "```" +
      "Hi! Here it is again:\n```product\n" + JSON.stringify(PRODUCT) + "\n```\nThanks";
    const segs = parseContent(content);
    // Two blocks, same id → exactly one card
    expect(cardTypes(segs)).toEqual(["product"]);
  });

  it("renders a two-product array as a single comparison card", () => {
    const content = "Comparison:\n```products\n" + JSON.stringify([PRODUCT, PRODUCT_2]) + "\n```";
    const segs = parseContent(content);
    expect(cardTypes(segs)).toEqual(["comparison"]);
  });

  it("renders 3+ products as individual product cards", () => {
    const content = "```products\n" + JSON.stringify([PRODUCT, PRODUCT_2, { ...PRODUCT, id: "x" }]) + "\n```";
    const segs = parseContent(content);
    expect(cardTypes(segs)).toEqual(["product", "product", "product"]);
  });

  it("does not misread a non-card fenced block as a card", () => {
    const content = "```python\nprint('product')\n```";
    const segs = parseContent(content);
    expect(cardTypes(segs)).toEqual([]);
  });

  it("does not match ```product-ideas (body not starting with { or [)", () => {
    const content = "```product-ideas\nsome list\n```";
    const segs = parseContent(content);
    expect(cardTypes(segs)).toEqual([]);
  });

  it("returns plain text untouched when there is no card", () => {
    const content = "Just a normal answer with no structured data.";
    const segs = parseContent(content);
    expect(cardTypes(segs)).toEqual([]);
    expect(textOf(segs)).toContain("normal answer");
  });

  it("parses a collapsed order fence", () => {
    const order = { id: "48bfb7a1-0b02-4c89-94c9-552d629aaa92", status: "shipped", total: 299.99, carrier: "Overnight Shipping", tracking: "TRK277303722" };
    const content = "Your order:```order" + JSON.stringify(order) + "```Anything else?";
    const segs = parseContent(content);
    expect(cardTypes(segs)).toEqual(["order"]);
  });
});
