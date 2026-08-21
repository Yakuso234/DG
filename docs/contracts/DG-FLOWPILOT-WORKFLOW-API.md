# DG FlowPilot Workflow API Contract

This contract covers the local interview-demo workflow runtime. It does not
claim a production DG-to-SW write integration.

## Runtime configuration

The module-level FastAPI application enables the workflow runtime only when all
required settings are explicit:

```text
FLOWPILOT_DATABASE_URL=postgresql://...
FLOWPILOT_WORKFLOW_ENABLED=true
FLOWPILOT_CHECKPOINT_PATH=C:\absolute\path\flowpilot-checkpoints.sqlite
FLOWPILOT_ACTION_RUNNER=sw-video-recovery
FLOWPILOT_SW_OPS_TRANSPORT=mcp
SW_VIDEO_MCP_URL=http://127.0.0.1:9010/mcp
SW_VIDEO_SERVICE_TOKEN=...
```

`FLOWPILOT_SW_OPS_TRANSPORT` defaults to `direct-http`. In that mode use
`SW_VIDEO_BASE_URL=http://localhost:...`; in `mcp` mode use the streamable HTTP
endpoint in `SW_VIDEO_MCP_URL`. Both modes require the service token. The MCP
client disables ambient proxy settings so local service-to-service calls cannot
silently leave the loopback/private network.

The optional structured-model setting is explicit and has no implicit network
or API-key fallback:

```text
FLOWPILOT_STRUCTURED_MODEL=deterministic  # default
# or
FLOWPILOT_STRUCTURED_MODEL=fake           # deterministic test double
```

The model can only suggest triage fields and the already-whitelisted recovery
action. FlowPilot constructs the Evidence references and immutable execution
scope itself, recomputes risk from `ACTION_CATALOG`, then still requires human
approval before any write call. A real provider is deliberately not enabled yet.

Optional non-secret internal actor identifiers:

```text
FLOWPILOT_HANDLER_ACTOR_ID=flowpilot-handler
FLOWPILOT_EXECUTOR_ACTOR_ID=flowpilot-action-executor
SW_VIDEO_SERVICE_NAME=flowpilot
```

## API authentication modes

`FLOWPILOT_AUTH_MODE=headers` is the default for the local Mock Demo and
legacy contract tests. It reads `x-user-id` / `x-user-role` and is explicitly
not a trusted deployment mode.

Set `FLOWPILOT_AUTH_MODE=jwt-local` to require a signed HS256 Bearer access
token for every non-health FlowPilot API route:

```text
FLOWPILOT_AUTH_MODE=jwt-local
FLOWPILOT_JWT_SECRET=<at-least-32-byte-secret>
FLOWPILOT_JWT_ISSUER=https://auth.example.internal
FLOWPILOT_JWT_AUDIENCE=flowpilot-api
```

The token must contain `exp`, `sub`, `role`, and `type=access`; `user_id` is
used as the stable Actor ID when present, otherwise `sub` is used. `role` must
be a FlowPilot role (`submitter`, `handler`, `approver`, `admin`, `service`).
In jwt-local mode, all `x-user-*` / `x-agent-*` headers are ignored. Missing,
expired, invalid, wrong-audience, or wrong-role tokens fail with HTTP 401.
This is a local HS256 boundary; production federation/JWKS remains a separate
future integration.

If `FLOWPILOT_WORKFLOW_ENABLED` is not true, the normal ticket API remains
available but workflow start/approval endpoints return HTTP 503. If it is true,
missing checkpoint or SW service-identity settings fail application startup.

The default `BusinessActionRunner` remains `MockBusinessActionRunner`, so a
safe no-network demo is always available. Setting
`FLOWPILOT_ACTION_RUNNER=sw-video-recovery` selects the real DG client adapter;
any other value fails startup. The real adapter only accepts
`recover_expired_video_processing` and is not exposed as an MCP tool.

## Start a ticket workflow

```http
POST /api/workflows/tickets/{ticket_id}/start
X-User-Id: u-handler
X-User-Role: handler
X-Trace-Id: trace-demo-1
Content-Type: application/json

{
  "creator_id": 7,
  "video_id": 9,
  "trace_id": "trace-demo-1",
  "thread_id": "ticket-{ticket_id}"
}
```

The API generates a `X-Trace-Id` for every request and returns it on every
response. A caller may provide a 1-128 character trace containing only letters,
numbers, `.`, `_`, `:`, or `-`. For workflow start, a supplied body `trace_id`
must match a supplied `X-Trace-Id`; otherwise the request is rejected with 422.
When the body field is omitted, the request TraceId is used. This prevents the
HTTP request, graph Evidence, MCP/SW propagation, and later logs from being
silently split across multiple correlation IDs.

The service advances `NEW -> TRIAGED -> INVESTIGATING`, runs the LangGraph
investigation, validates and persists Evidence/ActionProposal, then advances
`PROPOSED -> WAITING_APPROVAL`. A PROCESSING snapshot without lease evidence is
rejected. The graph must return an interrupt before the service accepts its
outputs.

## Decide and resume

```http
POST /api/workflows/proposals/{proposal_id}/approvals
X-User-Id: u-approver
X-User-Role: approver
Content-Type: application/json

{
  "decision": "approved",
  "thread_id": "ticket-{ticket_id}",
  "note": "confirmed for interview demo"
}
```

The approval is persisted before graph resume. The persisted proposal ID and
decision must match the resumed checkpoint. Approved/modified decisions move
through `EXECUTING` and the idempotent executor to `RESOLVED` or `FAILED`.
Denied decisions move to `ESCALATED` without invoking the executor.

## Current boundaries

- Phase 1 request headers are not production authentication; JWT replacement is pending.
- SQLite checkpoint is for a local single-instance demo, not multi-replica deployment.
- Start retries reuse a paused checkpoint and treat identical Evidence/Proposal IDs as idempotent.
- The complete FlowPilot suite has been verified against PostgreSQL 16 through Testcontainers; this is local integration evidence, not production load evidence.
- DG's approved recovery client is implemented against SW's existing `recover-expired` API.
- The Investigation gateway can use a real MCP `ClientSession` over Streamable HTTP; the
  local protocol regression starts FastMCP on loopback and keeps the SW gateway mocked.
- SW inbound token/idempotency-header verification and a live two-project integration run remain pending.
