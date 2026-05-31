/**
 * Demo scenario registry — the 8 scenarios from the README surfaced as
 * one-click launchers on the landing page, home dashboard, and Cmd-K palette.
 *
 * Each scenario deep-links into chat with the prompt prefilled so a recruiter
 * can run through the entire multi-agent flow in under a minute.
 */

import {
  Search,
  GitCompare,
  Package,
  RotateCcw,
  TrendingDown,
  Star,
  Warehouse,
  Shuffle,
  type LucideIcon,
} from "lucide-react";

export interface Scenario {
  id: string;
  label: string;
  /** One-line description of what this demonstrates. */
  description: string;
  /** Full prompt sent to chat. */
  prompt: string;
  /** Specialist agents this scenario exercises (display labels). */
  agents: string[];
  icon: LucideIcon;
}

export const DEMO_SCENARIOS: Scenario[] = [
  {
    id: "product-search",
    label: "Product Search",
    description: "Semantic search + price filtering across the catalog",
    prompt: "Find me wireless headphones under $300 with good noise cancellation",
    agents: ["Product Discovery"],
    icon: Search,
  },
  {
    id: "comparison",
    label: "Side-by-Side Comparison",
    description: "Compare two products on specs, price, and reviews",
    prompt: "Compare the Sony WH-1000XM5 with AirPods Max",
    agents: ["Product Discovery", "Review & Sentiment"],
    icon: GitCompare,
  },
  {
    id: "order-tracking",
    label: "Order Tracking",
    description: "Real-time order status and shipment location",
    prompt: "Where's my latest order?",
    agents: ["Order Management"],
    icon: Package,
  },
  {
    id: "return-flow",
    label: "Return Flow",
    description: "Full return eligibility check and initiation",
    prompt: "I want to return my last order",
    agents: ["Order Management"],
    icon: RotateCcw,
  },
  {
    id: "price-check",
    label: "Price Intelligence",
    description: "30-day price trend + deal quality signal",
    prompt: "Is the Logitech MX Master 3S a good deal right now?",
    agents: ["Pricing & Promotions", "Product Discovery"],
    icon: TrendingDown,
  },
  {
    id: "review-analysis",
    label: "Review Analysis",
    description: "Sentiment breakdown, topics, and fake-review detection",
    prompt: "What do people think about the Dyson V15?",
    agents: ["Review & Sentiment"],
    icon: Star,
  },
  {
    id: "stock-check",
    label: "Stock & Fulfillment",
    description: "Live inventory levels across all regional warehouses",
    prompt: "Is the Dyson V15 Detect in stock?",
    agents: ["Inventory & Fulfillment"],
    icon: Warehouse,
  },
  {
    id: "multi-intent",
    label: "Multi-Intent",
    description: "Single prompt — orchestrator fans out to multiple specialists",
    prompt: "Return my jacket and find me a warmer one under $200",
    agents: ["Order Management", "Product Discovery"],
    icon: Shuffle,
  },
];

/**
 * The first four scenarios as plain label/prompt pairs — used by the quick-
 * prompt chip row on the home dashboard (backward-compatible shape).
 */
export const QUICK_PROMPTS = DEMO_SCENARIOS.slice(0, 4).map(({ label, prompt }) => ({
  label,
  prompt,
}));

/** Build a chat deep-link that prefills the composer with a prompt. */
export function chatPromptHref(prompt: string): string {
  return `/chat?prompt=${encodeURIComponent(prompt)}`;
}

/** Build a public assistant deep-link (no auth required). */
export function shopAssistantHref(prompt: string): string {
  return `/shop/assistant?prompt=${encodeURIComponent(prompt)}`;
}
