/**
 * Quick-prompt scenarios surfaced on the home dashboard (and reusable by the
 * command palette / landing). Each deep-links into chat with the prompt.
 */
export interface Scenario {
  label: string;
  prompt: string;
}

export const QUICK_PROMPTS: Scenario[] = [
  { label: "Find wireless headphones", prompt: "Find me wireless headphones under $300" },
  { label: "Track my latest order", prompt: "What's the status of my latest order?" },
  { label: "Today's best deals", prompt: "Show me today's best deals" },
  { label: "Recommend a gift", prompt: "Recommend a gift for a coffee lover" },
];

/** Build a chat deep-link that prefills the composer with a prompt. */
export function chatPromptHref(prompt: string): string {
  return `/chat?prompt=${encodeURIComponent(prompt)}`;
}
