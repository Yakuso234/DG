"""MAF framework-native checkpoint + HITL probes (evidence for §7.2).

Two deterministic (no-LLM) demonstrations:

* ``FileCheckpointStorage`` — MAF's official file-based checkpoint storage.
  Executor state snapshots via ``on_checkpoint_save`` / ``on_checkpoint_restore``
  are persisted to JSON files and restored into a *fresh* workflow instance
  (cross-"process" recovery, tied to ``workflow_name`` + graph signature).
* ``request_info`` / ``@response_handler`` — MAF's Human-in-the-Loop pause and
  resume mechanism (caller supplies the human answer via ``responses={id: ...}``).

NOTE: MAF 1.0 validates ``WorkflowContext`` type arguments at import time, so
this module deliberately avoids ``from __future__ import annotations`` and uses
``typing.Never`` (not ``None``) for "no message / no output" slots.
"""

from dataclasses import dataclass
from typing import Any, Never

from agent_framework import (
    Executor,
    FileCheckpointStorage,
    WorkflowBuilder,
    WorkflowContext,
    handler,
    response_handler,
)

CHECKPOINT_WORKFLOW = "ticket-approval-workflow"


class StatusAccumulator(Executor):
    """Holds a ticket status string and snapshots it via on_checkpoint_save."""

    def __init__(self, seed: str) -> None:
        super().__init__(id="status-accumulator")
        self.status = seed

    @handler
    async def handle(self, next_status: str, ctx: WorkflowContext[str]) -> None:
        self.status = next_status
        await ctx.send_message(self.status)

    async def on_checkpoint_save(self) -> dict[str, Any]:
        return {"status": self.status}

    async def on_checkpoint_restore(self, state: dict[str, Any]) -> None:
        self.status = str(state.get("status", "NEW"))


class Finalizer(Executor):
    """Stateless terminal node: yields whatever status it receives."""

    def __init__(self) -> None:
        super().__init__(id="finalizer")

    @handler
    async def handle(self, status: str, ctx: WorkflowContext[Never, str]) -> None:
        await ctx.yield_output(status)


def build_checkpoint_workflow(storage: FileCheckpointStorage, *, seed: str):
    acc = StatusAccumulator(seed)
    fin = Finalizer()
    return (
        WorkflowBuilder(
            start_executor=acc,
            name=CHECKPOINT_WORKFLOW,
            checkpoint_storage=storage,
        )
        .add_edge(acc, fin)
        .build()
    )


async def run_checkpoint_workflow(
    storage: FileCheckpointStorage, *, seed: str, next_status: str
) -> str:
    """Run the workflow end to end and return the final yielded status."""
    workflow = build_checkpoint_workflow(storage, seed=seed)
    outputs: list[Any] = []
    async for event in workflow.run(next_status, stream=True):
        if getattr(event, "type", None) == "output":
            outputs.append(getattr(event, "data", None))
    return str(outputs[-1]) if outputs else ""


async def resume_checkpoint_workflow(
    storage: FileCheckpointStorage, checkpoint_id: str, *, resume_seed: str
) -> str:
    """Build a fresh workflow (different seed) and resume from a checkpoint."""
    workflow = build_checkpoint_workflow(storage, seed=resume_seed)
    outputs: list[Any] = []
    async for event in workflow.run(
        stream=True,
        checkpoint_id=checkpoint_id,
        checkpoint_storage=storage,
    ):
        if getattr(event, "type", None) == "output":
            outputs.append(getattr(event, "data", None))
    return str(outputs[-1]) if outputs else ""


@dataclass(frozen=True)
class ApprovalRequest:
    """Request data sent to the human during a HITL pause."""

    prompt: str


class ApprovalGate(Executor):
    """Pauses for a human approval answer, then yields the decision."""

    def __init__(self) -> None:
        super().__init__(id="approval-gate")

    @handler
    async def start(self, prompt: str, ctx: WorkflowContext[Never, str]) -> None:
        await ctx.request_info(
            request_data=ApprovalRequest(prompt=prompt),
            response_type=str,
        )

    @response_handler
    async def approve(
        self,
        request: ApprovalRequest,
        approval: str,
        ctx: WorkflowContext[Never, str],
    ) -> None:
        await ctx.yield_output(f"approval={approval}")


def build_hitl_workflow():
    return WorkflowBuilder(start_executor=ApprovalGate()).build()


async def run_hitl_with_response(prompt: str, approval: str) -> str:
    """Run the HITL workflow once, feed the canned approval, return output."""
    workflow = build_hitl_workflow()
    pending_request_id: str | None = None
    async for event in workflow.run(prompt, stream=True):
        if pending_request_id is None and getattr(event, "type", None) == "request_info":
            pending_request_id = getattr(event, "request_id", None)

    assert pending_request_id, "expected a request_info event to pause the workflow"

    outputs: list[Any] = []
    async for event in workflow.run(responses={pending_request_id: approval}, stream=True):
        if getattr(event, "type", None) == "output":
            outputs.append(getattr(event, "data", None))
    return str(outputs[-1]) if outputs else ""
