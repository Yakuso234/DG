import { describe, expect, it } from "vitest";
import { QUICK_PROMPTS, chatPromptHref } from "./scenarios";

describe("scenarios", () => {
  it("exposes a non-empty quick-prompt list", () => {
    expect(QUICK_PROMPTS.length).toBeGreaterThan(0);
    for (const s of QUICK_PROMPTS) {
      expect(s.label).toBeTruthy();
      expect(s.prompt).toBeTruthy();
    }
  });

  it("builds an encoded chat deep-link", () => {
    expect(chatPromptHref("find a gift & deal")).toBe(
      "/chat?prompt=find%20a%20gift%20%26%20deal",
    );
  });
});
