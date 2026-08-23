export type FlowPilotTicket = {
  id: string;
  title: string;
  description: string;
  priority: number;
  status: string;
  submitter: string;
  assignee: string | null;
  version: number;
  created_at: string;
  updated_at: string;
};

export type FlowPilotEvidence = {
  id: string;
  ticket_id: string;
  tool: string;
  source: string;
  data: Record<string, unknown>;
  collected_at: string;
};

export type FlowPilotProposal = {
  id: string;
  ticket_id: string;
  action: string;
  params: Record<string, unknown>;
  evidence_ids: string[];
  risk: "low" | "high";
  status: "proposed" | "approved" | "denied" | "executed";
  created_by: string;
  created_at: string;
};

export type FlowPilotRun = {
  id: string;
  ticket_id: string;
  agent: string;
  input_summary: string;
  output: Record<string, unknown>;
  model: string | null;
  tokens: { input_tokens?: number; output_tokens?: number; total_tokens?: number; calls?: number } | null;
  latency_ms: number | null;
  trace_id: string;
  created_at: string;
};

export type FlowPilotAuditEvent = {
  id: string;
  entity: string;
  entity_id: string;
  action: string;
  actor: string;
  actor_role: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  created_at: string;
};

export type FlowPilotTicketSnapshot = {
  ticket: FlowPilotTicket;
  evidence: FlowPilotEvidence[];
  proposals: FlowPilotProposal[];
  runs: FlowPilotRun[];
  audit: FlowPilotAuditEvent[];
};

const API_URL = process.env.NEXT_PUBLIC_FLOWPILOT_API_URL || "http://127.0.0.1:8090";

/**
 * 独立工作台只面向本地 Demo。真实部署必须使用 FLOWPILOT_AUTH_MODE=jwt-local，
 * 并由登录态提供 Bearer token；这里不复用上游商城的 JWT/电商身份模型。
 */
const LOCAL_ADMIN_HEADERS = {
  "x-user-id": "flowpilot-workbench-admin",
  "x-user-role": "admin",
};

export class FlowPilotApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function errorMessage(response: Response): Promise<string> {
  const payload: unknown = await response.json().catch(() => null);
  if (payload && typeof payload === "object" && "detail" in payload && typeof payload.detail === "string") {
    return payload.detail;
  }
  return `FlowPilot API 请求失败（HTTP ${response.status}）`;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        ...LOCAL_ADMIN_HEADERS,
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...(init.headers || {}),
      },
    });
  } catch (reason) {
    const detail = reason instanceof Error ? reason.message : "unknown network error";
    throw new FlowPilotApiError(`${path}: 无法连接 FlowPilot API（${detail}）`, 0);
  }
  if (!response.ok) throw new FlowPilotApiError(await errorMessage(response), response.status);
  return response.json() as Promise<T>;
}

export function threadIdForProposal(runs: FlowPilotRun[], proposalId: string): string | null {
  const run = runs.find(
    (item) => item.output.proposal_id === proposalId && typeof item.output.thread_id === "string",
  );
  return typeof run?.output.thread_id === "string" ? run.output.thread_id : null;
}

export const flowPilotApi = {
  listTickets: () => request<FlowPilotTicket[]>("/api/tickets"),
  getSnapshot: async (ticketId: string): Promise<FlowPilotTicketSnapshot> => {
    const [ticket, evidence, proposals, runs, audit] = await Promise.all([
      request<FlowPilotTicket>(`/api/tickets/${ticketId}`),
      request<FlowPilotEvidence[]>(`/api/tickets/${ticketId}/evidence`),
      request<FlowPilotProposal[]>(`/api/tickets/${ticketId}/proposals`),
      request<FlowPilotRun[]>(`/api/tickets/${ticketId}/runs`),
      request<FlowPilotAuditEvent[]>(`/api/audit/ticket/${ticketId}`),
    ]);
    return { ticket, evidence, proposals, runs, audit };
  },
  decideWorkflowApproval: (proposalId: string, threadId: string, decision: "approved" | "denied") =>
    request<{ ticket_target: string }>(`/api/workflows/proposals/${proposalId}/approvals`, {
      method: "POST",
      body: JSON.stringify({
        decision,
        thread_id: threadId,
        note: "FlowPilot local workbench decision",
      }),
    }),
};
