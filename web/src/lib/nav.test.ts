import { describe, expect, it } from "vitest";
import { visibleGroups, labelForPath } from "./nav";

describe("visibleGroups", () => {
  it("hides admin and seller items from a plain customer", () => {
    const groups = visibleGroups({ isAdmin: false, isSeller: false });
    const labels = groups.flatMap((g) => g.items.map((i) => i.label));
    expect(labels).toContain("Chat");
    expect(labels).toContain("Marketplace");
    expect(labels).not.toContain("Usage"); // adminOnly
    expect(labels).not.toContain("Seller"); // sellerOnly
    // the Admin group has no visible items, so it is dropped entirely
    expect(groups.find((g) => g.label === "Admin")).toBeUndefined();
  });

  it("shows seller items to a seller but not admin items", () => {
    const groups = visibleGroups({ isAdmin: false, isSeller: true });
    const labels = groups.flatMap((g) => g.items.map((i) => i.label));
    expect(labels).toContain("Seller");
    expect(labels).not.toContain("Usage");
  });

  it("shows everything to an admin", () => {
    const groups = visibleGroups({ isAdmin: true, isSeller: true });
    const labels = groups.flatMap((g) => g.items.map((i) => i.label));
    expect(labels).toContain("Usage");
    expect(labels).toContain("Audit");
    expect(labels).toContain("Seller");
  });
});

describe("labelForPath", () => {
  it("matches the most specific nav item", () => {
    expect(labelForPath("/admin/usage")).toBe("Usage");
    expect(labelForPath("/marketplace/my-agents")).toBe("My Agents");
    expect(labelForPath("/marketplace")).toBe("Marketplace");
  });

  it("matches nested detail routes to their parent item", () => {
    expect(labelForPath("/orders/abc-123")).toBe("Orders");
  });

  it("falls back to Home for unknown paths", () => {
    expect(labelForPath("/totally-unknown")).toBe("Home");
  });
});
