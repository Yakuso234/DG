"""只调用 Qwen Provider 的最小冒烟测试，不需要数据库、SW 或 Docker。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

from flowpilot.structured_model import (
    QwenStructuredFlowPilotModel,
    ResolutionModelInput,
    TriageModelInput,
    structured_model_from_env,
)


async def run_smoke() -> dict[str, object]:
    model = structured_model_from_env()
    if not isinstance(model, QwenStructuredFlowPilotModel):
        raise ValueError("Qwen 冒烟测试需要设置 FLOWPILOT_STRUCTURED_MODEL=qwen")

    triage = await model.triage(
        TriageModelInput(
            "smoke-ticket",
            7,
            901,
            "trace-qwen-smoke",
            "视频处理卡住",
            "lease 已过期，需判断是否进入人工审批",
        )
    )
    resolution = await model.resolve(
        ResolutionModelInput(
            "smoke-ticket",
            7,
            901,
            "trace-qwen-smoke",
            "视频处理卡住",
            "lease 已过期，需判断是否进入人工审批",
            "PROCESSING",
            "2026-08-20 09:00:00",
            1,
            "callback timeout",
        )
    )
    return {
        "provider": "qwen",
        "model": model.model_name,
        "triage": asdict(triage),
        "resolution": asdict(resolution),
    }


def main() -> None:
    try:
        result = asyncio.run(run_smoke())
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(f"Qwen smoke failed: {exc}") from None
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
