from __future__ import annotations

"""标准研究工作流的 runner 封装。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from central_bt.metrics import StandardMetrics, compute_standard_metrics
from central_bt.reports import write_standard_report
from central_bt.schema import BacktestResult, BacktestSpec, normalize_backtest_result


@dataclass
class StandardRunOutput:
    result: BacktestResult
    metrics: StandardMetrics
    artifacts: dict[str, str]


@dataclass
class StandardBacktestRunner:
    """执行策略 callable，并写出标准报告产物包。"""

    spec: BacktestSpec
    strategy: Callable[..., Any]
    output_dir: Path | str | None = None

    def run(self, *args: Any, **kwargs: Any) -> StandardRunOutput:
        raw = self.strategy(*args, **kwargs)
        result = normalize_backtest_result(raw, spec=self.spec)
        metrics = compute_standard_metrics(result)
        artifacts: dict[str, str] = {}
        if self.output_dir is not None:
            artifacts = write_standard_report(result, self.output_dir, metrics=metrics)
        return StandardRunOutput(result=result, metrics=metrics, artifacts=artifacts)

