"""模拟业务系统测试：确定性、可恢复异常、故障注入与写操作审计。"""

from __future__ import annotations

import pytest

from flowpilot.mock_business import FaultInjectedError, MockBusinessSystem, TransientError


@pytest.fixture
def biz() -> MockBusinessSystem:
    b = MockBusinessSystem()
    b.register("e-1", state="processing")
    return b


def test_status_query_is_deterministic(biz: MockBusinessSystem) -> None:
    first = biz.get_status("e-1")
    second = biz.get_status("e-1")
    assert first == second
    assert first["state"] == "processing"


def test_transient_error_recovers_on_retry(biz: MockBusinessSystem) -> None:
    biz.inject_fault("e-1", "flapping")
    with pytest.raises(TransientError):
        biz.get_status("e-1")
    # 重试成功
    status = biz.get_status("e-1")
    assert status["state"] == "processing"


def test_timeout_fault_is_injected_and_cleared(biz: MockBusinessSystem) -> None:
    biz.inject_fault("e-1", "timeout")
    with pytest.raises(FaultInjectedError):
        biz.get_status("e-1")
    biz.clear_faults("e-1")
    assert biz.get_status("e-1")["state"] == "processing"


def test_partial_failure_returns_structured_partial(biz: MockBusinessSystem) -> None:
    biz.inject_fault("e-1", "partial_failure")
    status = biz.get_status("e-1")
    assert status["partial"] is True
    assert "detail" in status


def test_restart_records_auditable_operation(biz: MockBusinessSystem) -> None:
    result = biz.restart_pipeline("e-1", force=True)
    assert result["ok"] is True
    assert len(biz.operations) == 1
    assert biz.operations[0]["op"] == "restart_pipeline"
    assert biz.operations[0]["force"] is True


def test_unknown_entity_and_fault_rejected(biz: MockBusinessSystem) -> None:
    with pytest.raises(KeyError):
        biz.get_status("missing")
    with pytest.raises(ValueError):
        biz.inject_fault("e-1", "not-a-fault")
