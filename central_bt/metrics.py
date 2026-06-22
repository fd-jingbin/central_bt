from __future__ import annotations

"""研究回测的标准绩效与风险指标。"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from central_bt.schema import BacktestResult


EPS = 1e-12


@dataclass
class StandardMetrics:
    summary: dict[str, Any]
    metric_table: pd.DataFrame
    monthly_returns: pd.DataFrame
    yearly_returns: pd.DataFrame
    drawdowns: pd.DataFrame
    rolling_metrics: pd.DataFrame


def _numeric(series: Any) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _finite_returns(series: Any) -> pd.Series:
    numeric = _numeric(series).replace([np.inf, -np.inf], np.nan)
    return numeric.dropna().astype(float)


def _safe_float(value: Any) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(numeric) if pd.notna(numeric) else float("nan")


def _safe_div(numerator: float, denominator: float) -> float:
    if not pd.notna(denominator) or abs(float(denominator)) <= EPS:
        return float("nan")
    return float(numerator) / float(denominator)


def _cumulative_return(returns: pd.Series) -> float:
    numeric = _finite_returns(returns)
    if numeric.empty:
        return float("nan")
    return float(numeric.sum())


def _annualized_return(returns: pd.Series, *, periods_per_year: float) -> float:
    numeric = _finite_returns(returns)
    if numeric.empty:
        return float("nan")
    return float(numeric.mean() * float(periods_per_year))


def _annualized_volatility(returns: pd.Series, *, periods_per_year: float) -> float:
    numeric = _finite_returns(returns)
    if numeric.empty:
        return float("nan")
    return float(numeric.std(ddof=0) * np.sqrt(float(periods_per_year)))


def _annualized_sharpe(returns: pd.Series, *, periods_per_year: float) -> float:
    numeric = _finite_returns(returns)
    if numeric.empty:
        return float("nan")
    vol = float(numeric.std(ddof=0))
    mean = float(numeric.mean())
    if vol <= EPS:
        if abs(mean) <= EPS:
            return 0.0
        return float(np.sign(mean) * 5.0)
    return float(np.sqrt(float(periods_per_year)) * mean / vol)


def _annualized_sortino(returns: pd.Series, *, periods_per_year: float) -> float:
    numeric = _finite_returns(returns)
    if numeric.empty:
        return float("nan")
    downside = numeric[numeric < 0.0]
    downside_vol = float(downside.std(ddof=0)) if not downside.empty else 0.0
    mean = float(numeric.mean())
    if downside_vol <= EPS:
        if abs(mean) <= EPS:
            return 0.0
        return float(np.sign(mean) * 5.0)
    return float(np.sqrt(float(periods_per_year)) * mean / downside_vol)


def _max_streak(mask: pd.Series) -> int:
    best = 0
    current = 0
    for value in mask.fillna(False).astype(bool).tolist():
        if value:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return int(best)


def _drawdown_components(returns: pd.Series, dates: pd.Series | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    numeric = _finite_returns(returns)
    if numeric.empty:
        return pd.DataFrame(columns=["Date", "Equity", "RunningPeak", "Drawdown"]), {
            "max_drawdown": float("nan"),
            "max_drawdown_start": None,
            "max_drawdown_end": None,
            "max_drawdown_duration": 0,
        }
    if dates is None:
        date_values = pd.Series(range(len(numeric)))
    else:
        date_values = pd.to_datetime(pd.Series(dates).iloc[numeric.index], errors="coerce").dt.normalize()
    cumulative = pd.Series(numeric.cumsum().to_numpy(dtype=float), index=numeric.index, dtype=float)
    equity = 1.0 + cumulative
    running_peak_return_values = np.maximum.accumulate(np.r_[0.0, cumulative.to_numpy(dtype=float)])[1:]
    running_peak = pd.Series(1.0 + running_peak_return_values, index=numeric.index, dtype=float)
    drawdown = cumulative - pd.Series(running_peak_return_values, index=numeric.index, dtype=float)
    trough_label = drawdown.idxmin()
    trough_pos = int(drawdown.index.get_loc(trough_label))
    peak_with_baseline_pos = int(np.argmax(np.r_[0.0, cumulative.iloc[: trough_pos + 1].to_numpy(dtype=float)]))
    peak_pos = peak_with_baseline_pos - 1
    peak_label = equity.index[peak_pos] if peak_pos >= 0 else None
    duration = trough_pos - peak_pos if peak_pos >= 0 else trough_pos + 1
    frame = pd.DataFrame(
        {
            "Date": date_values.to_numpy(),
            "Equity": equity.to_numpy(dtype=float),
            "RunningPeak": running_peak.to_numpy(dtype=float),
            "Drawdown": drawdown.to_numpy(dtype=float),
        }
    )
    return frame, {
        "max_drawdown": float(drawdown.min()),
        "max_drawdown_start": _date_or_none(date_values.loc[peak_label] if peak_label is not None and peak_label in date_values.index else None),
        "max_drawdown_end": _date_or_none(date_values.loc[trough_label] if trough_label in date_values.index else None),
        "max_drawdown_duration": int(duration),
    }


def _date_or_none(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    try:
        return str(pd.Timestamp(value).date())
    except (TypeError, ValueError):
        return str(value)


def _return_metrics(
    returns: pd.Series,
    *,
    dates: pd.Series | None,
    periods_per_year: float,
) -> dict[str, Any]:
    raw = _numeric(returns).replace([np.inf, -np.inf], np.nan)
    numeric = raw.dropna().astype(float)
    drawdown_frame, drawdown_summary = _drawdown_components(numeric, dates=dates)
    annualized_return = _annualized_return(numeric, periods_per_year=periods_per_year)
    max_drawdown = _safe_float(drawdown_summary.get("max_drawdown"))
    calmar = _safe_div(annualized_return, abs(max_drawdown)) if pd.notna(max_drawdown) and max_drawdown < 0 else float("nan")
    wins = numeric[numeric > 0.0]
    losses = numeric[numeric < 0.0]
    var_95 = float(np.quantile(numeric.to_numpy(dtype=float), 0.05)) if not numeric.empty else float("nan")
    var_99 = float(np.quantile(numeric.to_numpy(dtype=float), 0.01)) if not numeric.empty else float("nan")
    cvar_95 = float(numeric[numeric <= var_95].mean()) if not numeric.empty else float("nan")
    cvar_99 = float(numeric[numeric <= var_99].mean()) if not numeric.empty else float("nan")
    downside = losses
    return {
        "observation_count": int(len(numeric)),
        "missing_return_count": int(raw.isna().sum()),
        "sum_return": float(numeric.sum()) if not numeric.empty else float("nan"),
        "cumulative_return": _cumulative_return(numeric),
        "annualized_return": annualized_return,
        "annualized_volatility": _annualized_volatility(numeric, periods_per_year=periods_per_year),
        "downside_volatility": float(downside.std(ddof=0) * np.sqrt(float(periods_per_year))) if not downside.empty else 0.0,
        "sharpe": _annualized_sharpe(numeric, periods_per_year=periods_per_year),
        "sortino": _annualized_sortino(numeric, periods_per_year=periods_per_year),
        "calmar": calmar,
        "max_drawdown": max_drawdown,
        "max_drawdown_start": drawdown_summary.get("max_drawdown_start"),
        "max_drawdown_end": drawdown_summary.get("max_drawdown_end"),
        "max_drawdown_duration": drawdown_summary.get("max_drawdown_duration"),
        "average_drawdown": float(drawdown_frame["Drawdown"].mean()) if not drawdown_frame.empty else float("nan"),
        "hit_rate": float(numeric.gt(0.0).mean()) if not numeric.empty else float("nan"),
        "positive_day_count": int(numeric.gt(0.0).sum()),
        "negative_day_count": int(numeric.lt(0.0).sum()),
        "average_return": float(numeric.mean()) if not numeric.empty else float("nan"),
        "median_return": float(numeric.median()) if not numeric.empty else float("nan"),
        "best_return": float(numeric.max()) if not numeric.empty else float("nan"),
        "worst_return": float(numeric.min()) if not numeric.empty else float("nan"),
        "average_win": float(wins.mean()) if not wins.empty else float("nan"),
        "average_loss": float(losses.mean()) if not losses.empty else float("nan"),
        "win_loss_payoff": _safe_div(float(wins.mean()), abs(float(losses.mean()))) if not wins.empty and not losses.empty else float("nan"),
        "var_95": var_95,
        "cvar_95": cvar_95,
        "var_99": var_99,
        "cvar_99": cvar_99,
        "skew": float(numeric.skew()) if len(numeric) >= 3 else float("nan"),
        "kurtosis": float(numeric.kurt()) if len(numeric) >= 4 else float("nan"),
        "max_positive_streak": _max_streak(numeric.gt(0.0)),
        "max_negative_streak": _max_streak(numeric.lt(0.0)),
    }


def _comparison_metrics(
    primary: pd.Series,
    benchmark: pd.Series,
    *,
    periods_per_year: float,
) -> dict[str, Any]:
    aligned = pd.concat([_numeric(primary), _numeric(benchmark)], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if aligned.empty:
        return {}
    strategy = aligned.iloc[:, 0].astype(float)
    bench = aligned.iloc[:, 1].astype(float)
    active = strategy - bench
    bench_var = float(bench.var(ddof=0))
    beta = float(strategy.cov(bench) / bench_var) if bench_var > EPS else float("nan")
    active_std = float(active.std(ddof=0))
    tracking_error = float(active_std * np.sqrt(float(periods_per_year)))
    up_mask = bench.gt(0.0)
    down_mask = bench.lt(0.0)
    return {
        "observation_count": int(len(aligned)),
        "active_sum_return": float(active.sum()),
        "active_cumulative_return": _cumulative_return(strategy) - _cumulative_return(bench),
        "tracking_error": tracking_error,
        "information_ratio": float(np.sqrt(float(periods_per_year)) * active.mean() / active_std) if active_std > EPS else float("nan"),
        "correlation": float(strategy.corr(bench)) if len(aligned) >= 2 else float("nan"),
        "beta": beta,
        "annualized_alpha": float(float(periods_per_year) * (strategy.mean() - beta * bench.mean())) if pd.notna(beta) else float("nan"),
        "up_capture": _safe_div(float(strategy.loc[up_mask].sum()), float(bench.loc[up_mask].sum())) if up_mask.any() else float("nan"),
        "down_capture": _safe_div(float(strategy.loc[down_mask].sum()), float(bench.loc[down_mask].sum())) if down_mask.any() else float("nan"),
    }


def _exposure_metrics(result: BacktestResult) -> dict[str, Any]:
    daily = result.daily
    spec = result.spec
    metrics: dict[str, Any] = {}
    exposure_cols = {
        "gross": spec.gross_exposure_col,
        "long_gross": spec.long_exposure_col,
        "short_gross": spec.short_exposure_col,
        "net": spec.net_exposure_col,
        "net_ratio": spec.net_ratio_col,
        "names": spec.names_col,
    }
    for label, column in exposure_cols.items():
        if column not in daily.columns:
            continue
        series = _finite_returns(daily[column])
        if series.empty:
            continue
        metrics[f"average_{label}"] = float(series.mean())
        metrics[f"median_{label}"] = float(series.median())
        metrics[f"max_{label}"] = float(series.max())
        metrics[f"min_{label}"] = float(series.min())
    for column in ("DirectNameCoverage", "CoveredNameShare"):
        if column in daily.columns:
            series = _finite_returns(daily[column])
            if not series.empty:
                metrics[f"average_{column}"] = float(series.mean())
    return metrics


def _turnover_metrics(result: BacktestResult) -> dict[str, Any]:
    daily = result.daily
    column = result.spec.turnover_col
    if column not in daily.columns:
        return {}
    turnover = _finite_returns(daily[column])
    if turnover.empty:
        return {}
    return {
        "average_daily_turnover": float(turnover.mean()),
        "median_daily_turnover": float(turnover.median()),
        "p95_daily_turnover": float(np.quantile(turnover.to_numpy(dtype=float), 0.95)),
        "max_daily_turnover": float(turnover.max()),
        "annualized_turnover": float(turnover.mean() * float(result.spec.periods_per_year)),
        "trade_day_count": int(turnover.gt(0.0).sum()),
        "trade_day_share": float(turnover.gt(0.0).mean()),
    }


def _periodic_returns(
    daily: pd.DataFrame,
    *,
    date_col: str,
    return_cols: tuple[str, ...],
    freq: str,
    period_name: str,
) -> pd.DataFrame:
    if daily.empty:
        return pd.DataFrame(columns=[period_name, *return_cols])
    work = daily[[date_col, *[col for col in return_cols if col in daily.columns]]].copy()
    work[date_col] = pd.to_datetime(work[date_col], errors="coerce")
    work = work.dropna(subset=[date_col])
    if work.empty:
        return pd.DataFrame(columns=[period_name, *return_cols])
    work[period_name] = work[date_col].dt.to_period(freq).astype(str)
    rows: list[dict[str, Any]] = []
    for period, group in work.groupby(period_name, sort=True):
        row: dict[str, Any] = {period_name: period}
        for column in return_cols:
            if column in group.columns:
                row[column] = _cumulative_return(group[column])
        rows.append(row)
    return pd.DataFrame(rows)


def _rolling_metrics(
    daily: pd.DataFrame,
    *,
    date_col: str,
    return_cols: tuple[str, ...],
    periods_per_year: float,
    windows: tuple[int, ...] = (21, 63, 126),
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    dates = pd.to_datetime(daily[date_col], errors="coerce").dt.normalize()
    for column in return_cols:
        if column not in daily.columns:
            continue
        returns = _numeric(daily[column]).astype(float)
        for window in windows:
            if len(returns) < window:
                continue
            for end_pos in range(window - 1, len(returns)):
                window_returns = returns.iloc[end_pos - window + 1 : end_pos + 1]
                if window_returns.isna().all():
                    continue
                _, dd_summary = _drawdown_components(window_returns.dropna())
                rows.append(
                    {
                        "Date": dates.iloc[end_pos],
                        "ReturnColumn": column,
                        "Window": int(window),
                        "CumulativeReturn": _cumulative_return(window_returns),
                        "AnnualizedVolatility": _annualized_volatility(window_returns, periods_per_year=periods_per_year),
                        "Sharpe": _annualized_sharpe(window_returns, periods_per_year=periods_per_year),
                        "MaxDrawdown": dd_summary.get("max_drawdown"),
                    }
                )
    return pd.DataFrame(rows)


def _drawdown_frame(result: BacktestResult) -> pd.DataFrame:
    frame, _ = _drawdown_components(
        result.daily[result.spec.return_col],
        dates=result.daily[result.spec.date_col],
    )
    if not frame.empty:
        frame.insert(1, "ReturnColumn", result.spec.return_col)
    return frame


def _flatten_metrics(payload: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def visit(section: str, value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                visit(f"{section}.{key}" if section else str(key), item)
            return
        if isinstance(value, (list, tuple)):
            rows.append({"Section": section.rsplit(".", 1)[0], "Metric": section.rsplit(".", 1)[-1], "Value": ", ".join(str(item) for item in value)})
            return
        parent, _, metric = section.rpartition(".")
        rows.append({"Section": parent, "Metric": metric or section, "Value": value})

    visit("", payload)
    return pd.DataFrame(rows)


def compute_standard_metrics(result: BacktestResult) -> StandardMetrics:
    """为标准化回测计算规范指标包。"""

    spec = result.spec
    daily = result.daily
    date_series = daily[spec.date_col]
    primary = _return_metrics(
        daily[spec.return_col],
        dates=date_series,
        periods_per_year=spec.periods_per_year,
    )
    benchmarks = {
        column: _return_metrics(daily[column], dates=date_series, periods_per_year=spec.periods_per_year)
        for column in spec.benchmark_return_cols
        if column in daily.columns
    }
    comparisons = {
        column: _comparison_metrics(
            daily[spec.return_col],
            daily[column],
            periods_per_year=spec.periods_per_year,
        )
        for column in spec.benchmark_return_cols
        if column in daily.columns
    }
    leg_columns = tuple(
        column
        for column in ("LongLegReturn", "ShortLegReturn", "SelectionReturn", "NetTimingReturn")
        if column in daily.columns
    )
    legs = {
        column: _return_metrics(daily[column], dates=date_series, periods_per_year=spec.periods_per_year)
        for column in leg_columns
    }
    return_cols = tuple(dict.fromkeys((spec.return_col, *spec.benchmark_return_cols, *leg_columns)))
    data_quality = {
        "start_date": _date_or_none(date_series.min()),
        "end_date": _date_or_none(date_series.max()),
        "daily_rows": int(len(daily)),
        "duplicate_date_count": int(pd.to_datetime(date_series, errors="coerce").duplicated().sum()),
        "primary_return_col": spec.return_col,
        "benchmark_return_cols": tuple(column for column in spec.benchmark_return_cols if column in daily.columns),
    }
    summary = {
        "data_quality": data_quality,
        "primary": primary,
        "benchmarks": benchmarks,
        "benchmark_comparison": comparisons,
        "exposure": _exposure_metrics(result),
        "turnover": _turnover_metrics(result),
        "legs": legs,
    }
    monthly = _periodic_returns(
        daily,
        date_col=spec.date_col,
        return_cols=return_cols,
        freq="M",
        period_name="Month",
    )
    yearly = _periodic_returns(
        daily,
        date_col=spec.date_col,
        return_cols=return_cols,
        freq="Y",
        period_name="Year",
    )
    rolling = _rolling_metrics(
        daily,
        date_col=spec.date_col,
        return_cols=return_cols,
        periods_per_year=spec.periods_per_year,
    )
    return StandardMetrics(
        summary=summary,
        metric_table=_flatten_metrics(summary),
        monthly_returns=monthly,
        yearly_returns=yearly,
        drawdowns=_drawdown_frame(result),
        rolling_metrics=rolling,
    )

