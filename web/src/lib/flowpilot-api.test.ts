import { describe, expect, it } from "vitest";
import { threadIdForProposal, type FlowPilotRun } from "./flowpilot-api";

const run = (output: Record<string, unknown>): FlowPilotRun => ({
  id: "run-1",
  ticket_id: "ticket-1",
  agent: "flowpilot-main-graph",
  input_summary: "creator_id=7",
  output,
  model: "deterministic",
  tokens: null,
  latency_ms: 8,
  trace_id: "trace-1",
  created_at: "2026-08-23T00:00:00+00:00",
});

describe("threadIdForProposal", () => {
  it("only returns the persisted thread for the matching proposal", () => {
    expect(
      threadIdForProposal(
        [run({ proposal_id: "other", thread_id: "thread-other" }), run({ proposal_id: "p-1", thread_id: "thread-1" })],
        "p-1",
      ),
    ).toBe("thread-1");
  });

  it("fails closed for historical runs without a thread identifier", () => {
    expect(threadIdForProposal([run({ proposal_id: "p-1" })], "p-1")).toBeNull();
  });
});
