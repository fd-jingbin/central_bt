from __future__ import annotations

"""输入驱动的标准回测框架。"""

from central_bt.metrics import StandardMetrics, compute_standard_metrics
from central_bt.position_inputs import (
    PositionInputSpec,
    normalize_position_frame,
    normalize_return_frame,
    positions_from_trade_frame,
    run_backtest_from_position_input,
)
from central_bt.reports import write_standard_report
from central_bt.runner import StandardBacktestRunner, StandardRunOutput
from central_bt.schema import BacktestResult, BacktestSpec, normalize_backtest_result

__all__ = [
    "BacktestResult",
    "BacktestSpec",
    "PositionInputSpec",
    "StandardBacktestRunner",
    "StandardMetrics",
    "StandardRunOutput",
    "compute_standard_metrics",
    "normalize_backtest_result",
    "normalize_position_frame",
    "normalize_return_frame",
    "positions_from_trade_frame",
    "run_backtest_from_position_input",
    "write_standard_report",
]
