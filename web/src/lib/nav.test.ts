import { describe, expect, it } from "vitest";
import { visibleGroups, labelForPath } from "./nav";

describe("visibleGroups", () => {
  it("shows shop + account to a plain customer, hides admin/seller", () => {
    const groups = visibleGroups({ isAdmin: false, isSeller: false });
    const labels = groups.flatMap((g) => g.items.map((i) => i.label));
    expect(labels).toContain("Home");
    expect(labels).toContain("Chat");
    expect(labels).toContain("Agents"); // visible to all authenticated users
    expect(labels).toContain("Profile");
    expect(labels).not.toContain("Usage"); // adminOnly
    expect(labels).not.toContain("Seller"); // sellerOnly
    expect(labels).not.toContain("Marketplace");
    expect(groups.find((g) => g.label === "Admin")).toBeUndefined();
  });

  it("shows seller items to a seller but not admin items", () => {
    const groups = visibleGroups({ isAdmin: false, isSeller: true });
    const labels = groups.flatMap((g) => g.items.map((i) => i.label));
    expect(labels).toContain("Seller");
    expect(labels).not.toContain("Usage");
  });

  it("shows admin items (Usage, Audit) to an admin — no Requests", () => {
    const groups = visibleGroups({ isAdmin: true, isSeller: true });
    const labels = groups.flatMap((g) => g.items.map((i) => i.label));
    expect(labels).toContain("Usage");
    expect(labels).toContain("Audit");
    expect(labels).toContain("Seller");
    expect(labels).not.toContain("Requests"); // removed
  });
});

describe("labelForPath", () => {
  it("matches the most specific nav item", () => {
    expect(labelForPath("/admin/usage")).toBe("Usage");
    expect(labelForPath("/admin/audit")).toBe("Audit");
    expect(labelForPath("/admin")).toBe("Overview");
  });

  it("matches nested detail routes to their parent item", () => {
    expect(labelForPath("/orders/abc-123")).toBe("Orders");
    expect(labelForPath("/products/p1")).toBe("Products");
    expect(labelForPath("/agents/product-discovery")).toBe("Agents");
  });

  it("falls back to Home for unknown paths", () => {
    expect(labelForPath("/totally-unknown")).toBe("Home");
  });
});
