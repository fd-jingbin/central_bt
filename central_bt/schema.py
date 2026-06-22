from __future__ import annotations

"""共享回测结果契约。

研究代码可以保留自己的实现细节，但任何需要标准指标和报告的输出都应标准化为
``BacktestResult``。
"""

from dataclasses import dataclass, field, replace
from typing import Any, Mapping

import pandas as pd


_PRIMARY_RETURN_CANDIDATES = (
    "CentralBookReturn",
    "StrategyReturn",
    "PortfolioReturn",
    "BacktestReturn",
    "DailyReturn",
    "Return",
)
_NON_BENCHMARK_RETURN_COLUMNS = {
    "CentralBookCapitalReturn",
    "OvernightReturn",
    "IntradayReturn",
    "OpenSlippageReturn",
    "LongLegReturn",
    "ShortLegReturn",
    "SelectionReturn",
    "NetTimingReturn",
}


@dataclass(frozen=True)
class BacktestSpec:
    """研究运行的声明式契约。

    ``return_col`` 是主策略收益列。基准列是可选项，并会被过滤到日度数据中实际存在的列。
    """

    name: str
    variant: str = "default"
    research_owner: str = ""
    hypothesis: str = ""
    date_col: str = "Date"
    return_col: str = "CentralBookReturn"
    benchmark_return_cols: tuple[str, ...] = ("AllFundReturn", "SignalFundReturn")
    periods_per_year: float = 252.0
    gross_exposure_col: str = "CentralBookGrossStart"
    long_exposure_col: str = "LongGrossStart"
    short_exposure_col: str = "ShortGrossStart"
    net_exposure_col: str = "NetGrossStart"
    net_ratio_col: str = "NetRatioStart"
    turnover_col: str = "CentralBookTurnover"
    names_col: str = "Names"
    tags: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class BacktestResult:
    """供标准指标和报告消费的标准化输出。"""

    spec: BacktestSpec
    daily: pd.DataFrame
    summary: dict[str, Any] = field(default_factory=dict)
    decisions: pd.DataFrame = field(default_factory=pd.DataFrame)
    holdings: pd.DataFrame = field(default_factory=pd.DataFrame)
    trades: pd.DataFrame = field(default_factory=pd.DataFrame)
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    raw_metadata: dict[str, Any] = field(default_factory=dict)


def _infer_primary_return_col(daily: pd.DataFrame, preferred: str) -> str:
    if preferred and preferred in daily.columns:
        return preferred
    for column in _PRIMARY_RETURN_CANDIDATES:
        if column in daily.columns:
            return column
    for column in daily.columns:
        if str(column).endswith("Return") and str(column) not in _NON_BENCHMARK_RETURN_COLUMNS:
            return str(column)
    raise ValueError(
        "Cannot infer primary return column. Provide BacktestSpec(return_col=...) "
        "or include one of: " + ", ".join(_PRIMARY_RETURN_CANDIDATES)
    )


def _infer_benchmark_cols(
    daily: pd.DataFrame,
    *,
    primary_col: str,
    preferred: tuple[str, ...],
) -> tuple[str, ...]:
    selected: list[str] = []
    for column in preferred:
        if column in daily.columns and column != primary_col:
            selected.append(column)
    for column in daily.columns:
        text = str(column)
        if (
            text.endswith("Return")
            and text != primary_col
            and text not in _NON_BENCHMARK_RETURN_COLUMNS
            and text not in selected
        ):
            selected.append(text)
    return tuple(selected)


def _frame_or_empty(value: Any) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value.copy()
    return pd.DataFrame()


def _validate_and_sort_daily(daily: pd.DataFrame, spec: BacktestSpec) -> pd.DataFrame:
    if daily is None or daily.empty:
        raise ValueError("BacktestResult.daily must contain at least one row.")
    if spec.date_col not in daily.columns:
        raise ValueError(f"BacktestResult.daily is missing date column: {spec.date_col}")
    if spec.return_col not in daily.columns:
        raise ValueError(f"BacktestResult.daily is missing return column: {spec.return_col}")
    work = daily.copy()
    work[spec.date_col] = pd.to_datetime(work[spec.date_col], errors="coerce").dt.normalize()
    work = work.dropna(subset=[spec.date_col]).sort_values(spec.date_col, kind="mergesort").reset_index(drop=True)
    if work.empty:
        raise ValueError("BacktestResult.daily has no valid dates after normalization.")
    return work


def normalize_backtest_result(raw: Any, spec: BacktestSpec | None = None) -> BacktestResult:
    """把已有研究输出标准化为统一契约。

    接受的输入形态：

    - 已经标准化的 ``BacktestResult``
    - 现有 central_book 字典结果，包含 ``daily``、``summary``、``decisions``、
      ``holdings_history`` 和可选历史表
    - 任意至少包含 ``daily`` DataFrame 的字典
    """

    if isinstance(raw, BacktestResult):
        primary_col = _infer_primary_return_col(raw.daily, raw.spec.return_col)
        benchmark_cols = _infer_benchmark_cols(
            raw.daily,
            primary_col=primary_col,
            preferred=tuple(raw.spec.benchmark_return_cols),
        )
        normalized_spec = replace(raw.spec, return_col=primary_col, benchmark_return_cols=benchmark_cols)
        daily = _validate_and_sort_daily(raw.daily, normalized_spec)
        return BacktestResult(
            spec=normalized_spec,
            daily=daily,
            summary=dict(raw.summary or {}),
            decisions=_frame_or_empty(raw.decisions),
            holdings=_frame_or_empty(raw.holdings),
            trades=_frame_or_empty(raw.trades),
            tables={key: frame.copy() for key, frame in dict(raw.tables or {}).items() if isinstance(frame, pd.DataFrame)},
            raw_metadata=dict(raw.raw_metadata or {}),
        )

    if not isinstance(raw, dict):
        raise TypeError("normalize_backtest_result expects BacktestResult or dict-like research output.")

    daily = _frame_or_empty(raw.get("daily"))
    if daily.empty:
        raise ValueError("Raw backtest output must include a non-empty 'daily' DataFrame.")

    base_spec = spec or BacktestSpec(name=str(raw.get("name") or "central_book_backtest"))
    primary_col = _infer_primary_return_col(daily, base_spec.return_col)
    benchmark_cols = _infer_benchmark_cols(
        daily,
        primary_col=primary_col,
        preferred=tuple(base_spec.benchmark_return_cols),
    )
    normalized_spec = replace(base_spec, return_col=primary_col, benchmark_return_cols=benchmark_cols)
    daily = _validate_and_sort_daily(daily, normalized_spec)

    table_keys = (
        "weekly",
        "timing_history",
        "book_history",
        "stock_history",
        "current_book_scores",
        "current_stock_scores",
        "current_book_diagnostics",
        "current_stock_diagnostics",
        "current_timing_diagnostics",
    )
    tables = {
        key: raw[key].copy()
        for key in table_keys
        if isinstance(raw.get(key), pd.DataFrame) and not raw[key].empty
    }
    snapshot = raw.get("current_snapshot")
    if isinstance(snapshot, dict):
        for key, output_key in (
            ("book_scores", "current_book_scores"),
            ("stock_scores", "current_stock_scores"),
            ("book_diagnostics", "current_book_diagnostics"),
            ("stock_diagnostics", "current_stock_diagnostics"),
            ("timing_diagnostics", "current_timing_diagnostics"),
            ("target_portfolio", "current_target_portfolio"),
        ):
            value = snapshot.get(key)
            if isinstance(value, pd.DataFrame) and not value.empty:
                tables[output_key] = value.copy()

    return BacktestResult(
        spec=normalized_spec,
        daily=daily,
        summary=dict(raw.get("summary") or {}),
        decisions=_frame_or_empty(raw.get("decisions")),
        holdings=_frame_or_empty(raw.get("holdings") if "holdings" in raw else raw.get("holdings_history")),
        trades=_frame_or_empty(raw.get("trades")),
        tables=tables,
        raw_metadata={
            "raw_keys": sorted(str(key) for key in raw.keys()),
        },
    )

