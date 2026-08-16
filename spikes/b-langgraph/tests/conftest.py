"""pytest 公共配置。

1) 把 spikes/ 目录加入 sys.path，使 shared.domain 可直接 import。
2) 把 src/ 加入 sys.path（b_langgraph 包，防御性；uv 已 editable 安装）。
3) pytest_sessionfinish 时生成 report.json（合同第 6 节）。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# spikes/b-langgraph/tests -> parents[2] == spikes/
SPIKES_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = Path(__file__).resolve().parents[1] / "src"

for _dir in (SPIKES_DIR, SRC_DIR):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

_START = time.monotonic()


def pytest_configure(config: object) -> None:
    config.addinivalue_line("markers", "scenario(name): map test to SPIKE-001 scenario")


def pytest_sessionfinish(session: object, exitstatus: int) -> None:
    from b_langgraph.report import write_report

    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    results = {
        "S1": "FAIL",
        "S2": "FAIL",
        "S3": "FAIL",
        "S4": "FAIL",
        "S5a": "FAIL",
        "S5b": "SKIPPED-WITH-REASON",
    }

    node_scenario: dict[str, str] = {}
    for item in session.items:
        marker = item.get_closest_marker("scenario")
        if marker is not None:
            node_scenario[item.nodeid] = marker.args[0]

    for status in ("passed", "failed", "skipped", "error"):
        for report in reporter.stats.get(status, []):
            scenario = node_scenario.get(report.nodeid)
            if scenario is None:
                continue
            if status == "passed":
                results[scenario] = "PASS"
            elif status == "skipped":
                results[scenario] = "SKIPPED-WITH-REASON"
            elif status in ("failed", "error"):
                results[scenario] = "FAIL"

    report_path = Path(__file__).resolve().parents[1] / "report.json"
    write_report(report_path, results, exitstatus, time.monotonic() - _START)
