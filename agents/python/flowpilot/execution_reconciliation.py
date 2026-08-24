"""外部动作未知结果的可查询对账服务。

不把远端调用包装成分布式事务：SW 的持久化回执是事实源，DG 只以同一
Idempotency-Key 查询或安全重放，再用条件更新把本地状态收敛。
"""

from __future__ import annotations

from flowpilot.action_runner import ActionOutcomeUnknownError, BusinessActionRunner, ReconciliationOutcome
from flowpilot.db.repo import TicketRepo
from flowpilot.domain.models import ExecutionRecord
from flowpilot.domain.rbac import Actor, Role
from flowpilot.observability import flowpilot_span


class ExecutionReconciliationService:
    def __init__(
        self,
        repo: TicketRepo,
        action_runner: BusinessActionRunner,
        *,
        actor: Actor | None = None,
        max_attempts: int = 4,
        running_grace_seconds: int = 30,
    ) -> None:
        self._repo = repo
        self._runner = action_runner
        self._actor = actor or Actor("flowpilot-reconciliation", Role.SERVICE)
        self._max_attempts = max(1, max_attempts)
        self._running_grace_seconds = max(1, running_grace_seconds)

    async def reconcile(self, execution_id: str, *, actor: Actor | None = None) -> ExecutionRecord:
        """对单条未知/陈旧 running 执行立即对账；终态记录只读返回。"""
        effective_actor = actor or self._actor
        execution, proposal = await self._repo.reconciliation_item(effective_actor, execution_id)
        if execution.status not in {"unknown", "running"}:
            return execution
        with flowpilot_span(
            "flowpilot.action.reconcile",
            {
                "flowpilot.execution.id": execution.id,
                "flowpilot.proposal.id": proposal.id,
                "flowpilot.action": proposal.action,
                "flowpilot.reconcile.attempt": execution.reconcile_attempts + 1,
            },
        ):
            try:
                outcome = await self._runner.reconcile(proposal, idempotency_key=execution.idempotency_key)
            except ActionOutcomeUnknownError as exc:
                outcome = ReconciliationOutcome(
                    status="unknown",
                    result={"ok": False, "error_type": type(exc).__name__, "detail": str(exc), **exc.result},
                )
            except Exception as exc:
                # 对账器异常不是成功或明确业务拒绝，保持人工可见的未知状态。
                outcome = ReconciliationOutcome(
                    status="unknown",
                    result={"ok": False, "error_type": type(exc).__name__, "detail": str(exc)},
                )
            return await self._repo.reconcile_execution(
                effective_actor, execution.id, outcome, max_attempts=self._max_attempts
            )

    async def run_once(self, *, limit: int = 50) -> list[ExecutionRecord]:
        """处理一批到期 unknown 或超过 grace 的 running 记录。"""
        items = await self._repo.due_reconciliations(limit=limit, running_grace_seconds=self._running_grace_seconds)
        return [await self.reconcile(execution.id) for execution, _proposal in items]
