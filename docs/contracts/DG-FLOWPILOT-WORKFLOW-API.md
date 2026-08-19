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
SW_VIDEO_BASE_URL=http://localhost:...
SW_VIDEO_SERVICE_TOKEN=...
```

Optional non-secret internal actor identifiers:

```text
FLOWPILOT_HANDLER_ACTOR_ID=flowpilot-handler
FLOWPILOT_EXECUTOR_ACTOR_ID=flowpilot-action-executor
SW_VIDEO_SERVICE_NAME=flowpilot
```

If `FLOWPILOT_WORKFLOW_ENABLED` is not true, the normal ticket API remains
available but workflow start/approval endpoints return HTTP 503. If it is true,
missing checkpoint or SW service-identity settings fail application startup.

The current default `BusinessActionRunner` is `MockBusinessActionRunner`.
Reading SW status can therefore be real while the approved recovery action
remains deterministic and local. A real SW recovery adapter is a separate,
not-yet-completed contract.

## Start a ticket workflow

```http
POST /api/workflows/tickets/{ticket_id}/start
X-User-Id: u-handler
X-User-Role: handler
Content-Type: application/json

{
  "creator_id": 7,
  "video_id": 9,
  "trace_id": "trace-demo-1",
  "thread_id": "ticket-{ticket_id}"
}
```

The service advances `NEW -> TRIAGED -> INVESTIGATING`, runs the LangGraph
investigation, validates and persists Evidence/ActionProposal, then advances
`PROPOSED -> WAITING_APPROVAL`. The graph must return an interrupt before the
service accepts its outputs.

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
- Start-workflow recovery after a partial database write is not yet idempotent.
- PostgreSQL/Testcontainers verification must be rerun when Docker is available.
- SW inbound token verification and approved recovery API are not yet implemented in SW.
