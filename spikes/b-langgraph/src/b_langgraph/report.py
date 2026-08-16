"""report.json 生成（合同第 6 节）。

glue_lines = 本栈除 spikes/shared/ 与测试文件外的实现代码行数（非空行）。
monkeypatches = 对 site-packages/第三方包的改写列表（本实现为空，无任何改写）。
"""
from __future__ import annotations

import importlib.metadata
import json
import platform
from pathlib import Path
from typing import Any

SRC_DIR = Path(__file__).resolve().parent


def compute_glue_lines() -> int:
    """统计 src/b_langgraph/ 下实现代码的非空行数。"""
    total = 0
    for path in sorted(SRC_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        total += sum(1 for line in text.splitlines() if line.strip())
    return total


def collect_versions() -> dict[str, str]:
    """收集本栈关键依赖的实际版本。"""
    names = ["langgraph", "langgraph-checkpoint-sqlite", "mcp", "a2a-sdk"]
    versions: dict[str, str] = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "n/a"
    versions["agent-framework"] = "n/a (B 栈不使用)"
    return versions


def write_report(
    path: str | Path,
    scenarios: dict[str, str],
    pytest_exit_code: int,
    duration_seconds: float,
    monkeypatches: list[str] | None = None,
) -> dict[str, Any]:
    """写 report.json 并返回其内容。"""
    report = {
        "stack": "b-langgraph",
        "python": platform.python_version(),
        "scenarios": scenarios,
        "pytest_exit_code": pytest_exit_code,
        "duration_seconds": round(duration_seconds, 2),
        "deps": collect_versions(),
        "glue_lines": compute_glue_lines(),
        "monkeypatches": monkeypatches or [],
    }
    out = Path(path)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report
