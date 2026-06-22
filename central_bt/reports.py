from __future__ import annotations

"""标准回测报告渲染与产物写出。"""

from dataclasses import asdict
from datetime import datetime, timezone
import html
import json
from pathlib import Path
from typing import Any

import pandas as pd

from central_bt.metrics import StandardMetrics, compute_standard_metrics
from central_bt.schema import BacktestResult, normalize_backtest_result


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value).strip())
    return cleaned.strip("._") or "table"


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, pd.DataFrame):
        return [_to_jsonable(record) for record in value.to_dict("records")]
    if isinstance(value, pd.Series):
        return {str(key): _to_jsonable(item) for key, item in value.to_dict().items()}
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    if hasattr(value, "item") and callable(getattr(value, "item")):
        try:
            return _to_jsonable(value.item())
        except (TypeError, ValueError):
            return value
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return value
    return value


def _fmt_pct(value: Any, digits: int = 2) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "-"
    return f"{float(numeric):.{digits}%}"


def _fmt_num(value: Any, digits: int = 2) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "-"
    return f"{float(numeric):,.{digits}f}"


def _fmt_money(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "-"
    value_float = float(numeric)
    sign = "-" if value_float < 0 else ""
    abs_value = abs(value_float)
    if abs_value >= 1_000_000_000:
        return f"{sign}${abs_value / 1_000_000_000:,.2f}B"
    if abs_value >= 1_000_000:
        return f"{sign}${abs_value / 1_000_000:,.2f}M"
    if abs_value >= 1_000:
        return f"{sign}${abs_value / 1_000:,.1f}K"
    return f"{sign}${abs_value:,.0f}"


def _metric_rows(metrics: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        ("总收益", _fmt_pct(metrics.get("cumulative_return", metrics.get("sum_return")))),
        ("年化收益", _fmt_pct(metrics.get("annualized_return"))),
        ("年化波动率", _fmt_pct(metrics.get("annualized_volatility"))),
        ("Sharpe", _fmt_num(metrics.get("sharpe"))),
        ("Sortino", _fmt_num(metrics.get("sortino"))),
        ("Calmar", _fmt_num(metrics.get("calmar"))),
        ("最大回撤", _fmt_pct(metrics.get("max_drawdown"))),
        ("VaR 95", _fmt_pct(metrics.get("var_95"))),
        ("CVaR 95", _fmt_pct(metrics.get("cvar_95"))),
        ("胜率", _fmt_pct(metrics.get("hit_rate"))),
        ("最差单日", _fmt_pct(metrics.get("worst_return"))),
    ]


def _markdown_table(rows: list[tuple[str, str]], *, headers: tuple[str, str] = ("指标", "数值")) -> list[str]:
    lines = [f"| {headers[0]} | {headers[1]} |", "| --- | ---: |"]
    for key, value in rows:
        lines.append(f"| {key} | {value} |")
    return lines


def render_markdown_report(
    result: BacktestResult,
    metrics: StandardMetrics,
    *,
    generated_utc: str,
    artifacts: dict[str, str],
) -> str:
    spec = result.spec
    summary = metrics.summary
    primary = summary.get("primary", {})
    turnover = summary.get("turnover", {})
    exposure = summary.get("exposure", {})
    data_quality = summary.get("data_quality", {})
    lines: list[str] = [
        f"# 标准回测报告：{spec.name}",
        "",
        "## 研究契约",
        f"- Variant：`{spec.variant}`",
        f"- 负责人：{spec.research_owner or '-'}",
        f"- 生成时间 UTC：{generated_utc}",
        f"- 日期范围：{data_quality.get('start_date') or '-'} 到 {data_quality.get('end_date') or '-'}",
        f"- 主收益列：`{spec.return_col}`",
        f"- 基准：{', '.join(f'`{item}`' for item in data_quality.get('benchmark_return_cols', ())) or '-'}",
    ]
    if spec.hypothesis:
        lines.append(f"- 假设：{spec.hypothesis}")
    if spec.tags:
        lines.append(f"- 标签：{', '.join(spec.tags)}")
    lines.extend(["", "## 核心指标", *_markdown_table(_metric_rows(primary)), ""])

    benchmark_comparison = summary.get("benchmark_comparison", {})
    if benchmark_comparison:
        lines.extend(["## 基准比较", "| 基准 | 主动收益 | 跟踪误差 | 信息比率 | Beta | 相关性 |", "| --- | ---: | ---: | ---: | ---: | ---: |"])
        for benchmark, payload in benchmark_comparison.items():
            lines.append(
                f"| `{benchmark}` | {_fmt_pct(payload.get('active_sum_return'))} | "
                f"{_fmt_pct(payload.get('tracking_error'))} | {_fmt_num(payload.get('information_ratio'))} | "
                f"{_fmt_num(payload.get('beta'))} | {_fmt_num(payload.get('correlation'))} |"
            )
        lines.append("")

    if turnover or exposure:
        lines.extend(
            [
                "## 敞口与换手",
                "| 指标 | 数值 |",
                "| --- | ---: |",
                f"| 平均总敞口 | {_fmt_num(exposure.get('average_gross'), 0)} |",
                f"| 平均净敞口 | {_fmt_num(exposure.get('average_net'), 0)} |",
                f"| 平均净敞口比例 | {_fmt_pct(exposure.get('average_net_ratio'))} |",
                f"| 平均持仓数量 | {_fmt_num(exposure.get('average_names'))} |",
                f"| 平均日换手 | {_fmt_pct(turnover.get('average_daily_turnover'))} |",
                f"| 年化换手 | {_fmt_num(turnover.get('annualized_turnover'))}x |",
                f"| 交易日占比 | {_fmt_pct(turnover.get('trade_day_share'))} |",
                "",
            ]
        )

    legs = summary.get("legs", {})
    if legs:
        lines.extend(["## 多空腿指标", "| 收益列 | 总收益 | Sharpe | 最大回撤 | 胜率 |", "| --- | ---: | ---: | ---: | ---: |"])
        for column, payload in legs.items():
            lines.append(
                f"| `{column}` | {_fmt_pct(payload.get('sum_return'))} | {_fmt_num(payload.get('sharpe'))} | "
                f"{_fmt_pct(payload.get('max_drawdown'))} | {_fmt_pct(payload.get('hit_rate'))} |"
            )
        lines.append("")

    lines.extend(
        [
            "## 数据质量",
            f"- 日度行数：{data_quality.get('daily_rows', 0)}",
            f"- 重复日期：{data_quality.get('duplicate_date_count', 0)}",
            f"- 主收益缺失：{primary.get('missing_return_count', 0)}",
            "",
            "## 产物",
        ]
    )
    for name, path in artifacts.items():
        lines.append(f"- `{name}`: `{path}`")
    return "\n".join(lines) + "\n"


_CHART_COLORS = ("#2563eb", "#16a34a", "#dc2626", "#9333ea", "#ea580c", "#0891b2")


def _fmt_date(value: Any) -> str:
    if value is None or pd.isna(value):
        return "-"
    try:
        return str(pd.Timestamp(value).date())
    except (TypeError, ValueError):
        return str(value)


def _html_table(
    frame: pd.DataFrame,
    *,
    columns: list[str] | None = None,
    max_rows: int = 10,
    percent_cols: set[str] | None = None,
    money_cols: set[str] | None = None,
    numeric_digits: int = 4,
) -> str:
    if frame is None or frame.empty:
        return "<p class=\"muted\">无数据。</p>"
    percent_cols = percent_cols or set()
    money_cols = money_cols or set()
    work = frame.copy()
    if columns is not None:
        work = work[[column for column in columns if column in work.columns]]
    work = work.head(max_rows)
    for column in work.columns:
        if pd.api.types.is_datetime64_any_dtype(work[column]):
            work[column] = pd.to_datetime(work[column], errors="coerce").dt.date.astype(str)
        elif pd.api.types.is_numeric_dtype(work[column]):
            if column in percent_cols:
                work[column] = work[column].map(lambda value: _fmt_pct(value, 2))
            elif column in money_cols:
                work[column] = work[column].map(_fmt_money)
            else:
                work[column] = work[column].map(lambda value: _fmt_num(value, numeric_digits))
    return work.to_html(index=False, escape=True, classes="data-table", border=0)


def _kpi_card(label: str, value: str, detail: str = "") -> str:
    return (
        "<div class=\"kpi\">"
        f"<div class=\"kpi-label\">{html.escape(label)}</div>"
        f"<div class=\"kpi-value\">{html.escape(value)}</div>"
        f"<div class=\"kpi-detail\">{html.escape(detail)}</div>"
        "</div>"
    )


def _line_chart_svg(series_by_name: dict[str, pd.Series], *, title: str, percent_axis: bool = True) -> str:
    clean: dict[str, pd.Series] = {}
    for name, series in series_by_name.items():
        numeric = pd.to_numeric(series, errors="coerce").replace([float("inf"), float("-inf")], pd.NA).dropna()
        if not numeric.empty:
            clean[str(name)] = numeric.astype(float).reset_index(drop=True)
    if not clean:
        return "<p class=\"muted\">无可绘制数据。</p>"

    width = 900
    height = 260
    pad_left = 54
    pad_right = 20
    pad_top = 24
    pad_bottom = 36
    plot_width = width - pad_left - pad_right
    plot_height = height - pad_top - pad_bottom
    all_values = pd.concat(clean.values(), ignore_index=True)
    min_y = float(all_values.min())
    max_y = float(all_values.max())
    if abs(max_y - min_y) <= 1e-12:
        min_y -= 0.01
        max_y += 0.01
    padding = 0.08 * (max_y - min_y)
    min_y -= padding
    max_y += padding

    def x_at(pos: int, count: int) -> float:
        if count <= 1:
            return pad_left + plot_width / 2.0
        return pad_left + plot_width * (float(pos) / float(count - 1))

    def y_at(value: float) -> float:
        return pad_top + plot_height * (1.0 - ((float(value) - min_y) / (max_y - min_y)))

    y_ticks = [min_y, (min_y + max_y) / 2.0, max_y]
    lines: list[str] = [
        f"<svg class=\"chart\" viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"{html.escape(title)}\">",
        "<rect width=\"900\" height=\"260\" rx=\"6\" fill=\"#ffffff\"/>",
    ]
    for tick in y_ticks:
        y = y_at(tick)
        label = _fmt_pct(tick) if percent_axis else _fmt_num(tick)
        lines.append(f"<line x1=\"{pad_left}\" y1=\"{y:.2f}\" x2=\"{width - pad_right}\" y2=\"{y:.2f}\" stroke=\"#e5e7eb\"/>")
        lines.append(f"<text x=\"12\" y=\"{y + 4:.2f}\" class=\"axis-label\">{html.escape(label)}</text>")

    legend: list[str] = []
    for idx, (name, series) in enumerate(clean.items()):
        color = _CHART_COLORS[idx % len(_CHART_COLORS)]
        count = len(series)
        points = " ".join(f"{x_at(pos, count):.2f},{y_at(float(value)):.2f}" for pos, value in enumerate(series.tolist()))
        lines.append(f"<polyline fill=\"none\" stroke=\"{color}\" stroke-width=\"2.5\" points=\"{points}\"/>")
        last_x = x_at(count - 1, count)
        last_y = y_at(float(series.iloc[-1]))
        lines.append(f"<circle cx=\"{last_x:.2f}\" cy=\"{last_y:.2f}\" r=\"3.5\" fill=\"{color}\"/>")
        legend.append(
            f"<span class=\"legend-item\"><span class=\"legend-swatch\" style=\"background:{color}\"></span>{html.escape(name)}</span>"
        )
    lines.append(f"<line x1=\"{pad_left}\" y1=\"{height - pad_bottom}\" x2=\"{width - pad_right}\" y2=\"{height - pad_bottom}\" stroke=\"#cbd5e1\"/>")
    lines.append("</svg>")
    return "<div class=\"chart-wrap\">" + "".join(lines) + "<div class=\"legend\">" + "".join(legend) + "</div></div>"


def _return_curve_chart(result: BacktestResult) -> str:
    daily = result.daily
    spec = result.spec
    series_by_name: dict[str, pd.Series] = {}
    if spec.return_col in daily.columns:
        series_by_name[spec.return_col] = pd.to_numeric(daily[spec.return_col], errors="coerce").fillna(0.0).cumsum()
    for column in spec.benchmark_return_cols:
        if column in daily.columns:
            series_by_name[column] = pd.to_numeric(daily[column], errors="coerce").fillna(0.0).cumsum()
    return _line_chart_svg(series_by_name, title="累计收益")


def _drawdown_chart(metrics: StandardMetrics) -> str:
    if metrics.drawdowns.empty or "Drawdown" not in metrics.drawdowns.columns:
        return "<p class=\"muted\">无回撤数据。</p>"
    return _line_chart_svg({"回撤": metrics.drawdowns["Drawdown"]}, title="回撤")


def _bar_chart_svg(items: list[tuple[str, float]], *, title: str, value_type: str = "money") -> str:
    clean = [(str(label), float(value)) for label, value in items if pd.notna(value)]
    if not clean:
        return "<p class=\"muted\">无可绘制数据。</p>"
    width = 900
    row_height = 34
    pad_left = 150
    pad_right = 110
    pad_top = 24
    pad_bottom = 20
    height = pad_top + pad_bottom + row_height * len(clean)
    max_abs = max(abs(value) for _, value in clean) or 1.0
    zero_x = pad_left + (width - pad_left - pad_right) / 2.0
    scale = (width - pad_left - pad_right) / 2.0 / max_abs

    def fmt_value(value: float) -> str:
        if value_type == "pct":
            return _fmt_pct(value)
        if value_type == "num":
            return _fmt_num(value)
        return _fmt_money(value)

    lines = [
        f"<svg class=\"bar-chart\" viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"{html.escape(title)}\">",
        f"<rect width=\"{width}\" height=\"{height}\" rx=\"6\" fill=\"#ffffff\"/>",
        f"<line x1=\"{zero_x:.2f}\" y1=\"{pad_top - 6}\" x2=\"{zero_x:.2f}\" y2=\"{height - pad_bottom + 4}\" stroke=\"#cbd5e1\"/>",
    ]
    for idx, (label, value) in enumerate(clean):
        y = pad_top + idx * row_height
        bar_y = y + 7
        bar_width = abs(value) * scale
        x = zero_x if value >= 0 else zero_x - bar_width
        color = "#15803d" if value >= 0 else "#b91c1c"
        lines.append(f"<text x=\"12\" y=\"{y + 23}\" class=\"bar-label\">{html.escape(label)}</text>")
        lines.append(f"<rect x=\"{x:.2f}\" y=\"{bar_y}\" width=\"{bar_width:.2f}\" height=\"16\" rx=\"3\" fill=\"{color}\"/>")
        value_x = zero_x + bar_width + 8 if value >= 0 else zero_x - bar_width - 8
        anchor = "start" if value >= 0 else "end"
        lines.append(f"<text x=\"{value_x:.2f}\" y=\"{y + 21}\" text-anchor=\"{anchor}\" class=\"bar-value\">{html.escape(fmt_value(value))}</text>")
    lines.append("</svg>")
    return "<div class=\"chart-wrap\">" + "".join(lines) + "</div>"


def _exposure_chart(result: BacktestResult) -> str:
    daily = result.daily
    columns = {
        "总敞口": "CentralBookGrossStart",
        "多头": "LongGrossStart",
        "空头": "ShortGrossStart",
        "净敞口": "NetGrossStart",
    }
    series_by_name = {name: daily[column] for name, column in columns.items() if column in daily.columns}
    return _line_chart_svg(series_by_name, title="敞口", percent_axis=True)


def _turnover_chart(result: BacktestResult) -> str:
    daily = result.daily
    if "CentralBookTurnover" not in daily.columns:
        return "<p class=\"muted\">无换手数据。</p>"
    return _line_chart_svg({"换手": daily["CentralBookTurnover"]}, title="换手", percent_axis=True)


def _rolling_sharpe_chart(metrics: StandardMetrics) -> str:
    frame = metrics.rolling_metrics
    if frame.empty or "Sharpe" not in frame.columns:
        return "<p class=\"muted\">样本不足，无法计算滚动指标。</p>"
    work = frame[frame["Window"].eq(frame["Window"].min())].copy() if "Window" in frame.columns else frame.copy()
    if "ReturnColumn" in work.columns:
        primary = work["ReturnColumn"].iloc[0]
        work = work[work["ReturnColumn"].eq(primary)]
    return _line_chart_svg({"滚动 Sharpe": work["Sharpe"]}, title="滚动 Sharpe", percent_axis=False)


def _pnl_breakdown_items(result: BacktestResult) -> list[tuple[str, float]]:
    daily = result.daily
    component_defs = (
        ("原有仓位 PnL", "ExistingPositionPnL", 1.0),
        ("开盘调仓 PnL", "RebalancePnL", 1.0),
        ("开盘滑点", "OpenSlippageCost", -1.0),
        ("总 PnL", "CentralBookPnL", 1.0),
    )
    if "ExistingPositionPnL" not in daily.columns:
        component_defs = (
            ("隔夜 PnL", "OvernightPnL", 1.0),
            ("日内 PnL", "IntradayPnL", 1.0),
            ("开盘滑点", "OpenSlippageCost", -1.0),
            ("总 PnL", "CentralBookPnL", 1.0),
        )
    items: list[tuple[str, float]] = []
    for label, column, sign in component_defs:
        if column in daily.columns:
            items.append((label, sign * float(pd.to_numeric(daily[column], errors="coerce").fillna(0.0).sum())))
    return items


def _tail_events(result: BacktestResult, *, count: int = 5) -> pd.DataFrame:
    daily = result.daily.copy()
    if result.spec.return_col not in daily.columns:
        return pd.DataFrame()
    daily["_ReturnSort"] = pd.to_numeric(daily[result.spec.return_col], errors="coerce")
    best = daily.nlargest(count, "_ReturnSort")
    worst = daily.nsmallest(count, "_ReturnSort")
    out = pd.concat([best.assign(Bucket="最好"), worst.assign(Bucket="最差")], ignore_index=True)
    columns = [
        "Bucket",
        result.spec.date_col,
        result.spec.return_col,
        "CentralBookPnL",
        "CentralBookGrossStart",
        "CentralBookTurnover",
        "MissingReturnCount",
    ]
    return out[[column for column in columns if column in out.columns]]


def _ticker_contribution(result: BacktestResult, *, count: int = 12) -> pd.DataFrame:
    holdings = result.holdings
    if holdings is None or holdings.empty or "Ticker" not in holdings.columns:
        return pd.DataFrame()
    work = holdings.copy()
    for column in ("PnL", "OpenNotional", "TradeNotional", "OpenSlippageCost"):
        if column in work.columns:
            work[column] = pd.to_numeric(work[column], errors="coerce").fillna(0.0)
    agg_map: dict[str, str] = {}
    if "PnL" in work.columns:
        agg_map["PnL"] = "sum"
    if "OpenNotional" in work.columns:
        agg_map["OpenNotional"] = "mean"
    if "TradeNotional" in work.columns:
        agg_map["TradeNotional"] = "sum"
    if "OpenSlippageCost" in work.columns:
        agg_map["OpenSlippageCost"] = "sum"
    if not agg_map:
        return pd.DataFrame()
    grouped = work.groupby("Ticker", as_index=False).agg(agg_map)
    if "PnL" in grouped.columns:
        grouped = grouped.sort_values("PnL", key=lambda series: series.abs(), ascending=False)
    return grouped.head(count).reset_index(drop=True)


def _data_quality_rows(result: BacktestResult, metrics: StandardMetrics) -> list[tuple[str, str]]:
    summary = metrics.summary
    data_quality = summary.get("data_quality", {})
    exposure = summary.get("exposure", {})
    primary = summary.get("primary", {})
    return [
        ("日期范围", f"{data_quality.get('start_date') or '-'} 到 {data_quality.get('end_date') or '-'}"),
        ("日度行数", _fmt_num(data_quality.get("daily_rows"), 0)),
        ("重复日期", _fmt_num(data_quality.get("duplicate_date_count"), 0)),
        ("主收益缺失", _fmt_num(primary.get("missing_return_count"), 0)),
        ("平均直接覆盖率", _fmt_pct(exposure.get("average_DirectNameCoverage"))),
        ("平均覆盖名称占比", _fmt_pct(exposure.get("average_CoveredNameShare"))),
        ("收益定义", "日度 PnL / 期初总敞口；总收益为日收益累计和"),
    ]


def _simple_rows_table(rows: list[tuple[str, str]]) -> str:
    return pd.DataFrame(rows, columns=["指标", "数值"]).to_html(index=False, escape=True, classes="data-table", border=0)


def _readout_items(result: BacktestResult, metrics: StandardMetrics) -> str:
    summary = metrics.summary
    primary = summary.get("primary", {})
    exposure = summary.get("exposure", {})
    turnover = summary.get("turnover", {})
    items = [
        f"总收益为 {_fmt_pct(primary.get('cumulative_return', primary.get('sum_return')))}，基于总敞口归一化的日收益序列。",
        f"最大回撤为 {_fmt_pct(primary.get('max_drawdown'))}，区间为 {primary.get('max_drawdown_start') or '-'} 到 {primary.get('max_drawdown_end') or '-'}。",
        f"平均总敞口为 {_fmt_num(exposure.get('average_gross'), 2)}，平均净敞口比例为 {_fmt_pct(exposure.get('average_net_ratio'))}。",
        f"平均日换手为 {_fmt_pct(turnover.get('average_daily_turnover'))}；年化换手为 {_fmt_num(turnover.get('annualized_turnover'))}x。",
    ]
    return "<ul class=\"readout\">" + "".join(f"<li>{html.escape(item)}</li>" for item in items) + "</ul>"


def render_html_report(
    result: BacktestResult,
    metrics: StandardMetrics,
    *,
    generated_utc: str,
    artifacts: dict[str, str] | None = None,
) -> str:
    spec = result.spec
    summary = metrics.summary
    artifacts = artifacts or {}
    primary = summary.get("primary", {})
    exposure = summary.get("exposure", {})
    turnover = summary.get("turnover", {})
    data_quality = summary.get("data_quality", {})
    primary_table = pd.DataFrame(_metric_rows(primary), columns=["指标", "数值"]).to_html(index=False, escape=True, classes="data-table", border=0)
    comparison_rows = []
    for benchmark, payload in summary.get("benchmark_comparison", {}).items():
        comparison_rows.append(
            {
                "基准": benchmark,
                "主动收益": _fmt_pct(payload.get("active_sum_return")),
                "跟踪误差": _fmt_pct(payload.get("tracking_error")),
                "信息比率": _fmt_num(payload.get("information_ratio")),
                "Beta": _fmt_num(payload.get("beta")),
                "相关性": _fmt_num(payload.get("correlation")),
            }
        )
    comparison_html = (
        pd.DataFrame(comparison_rows).to_html(index=False, escape=True, classes="data-table", border=0)
        if comparison_rows
        else "<p class=\"muted\">未提供基准。</p>"
    )
    exposure_rows = [
        ("平均总敞口", _fmt_num(exposure.get("average_gross"), 2)),
        ("平均净敞口", _fmt_num(exposure.get("average_net"), 2)),
        ("平均净敞口比例", _fmt_pct(exposure.get("average_net_ratio"))),
        ("平均持仓数量", _fmt_num(exposure.get("average_names"), 2)),
        ("平均日换手", _fmt_pct(turnover.get("average_daily_turnover"))),
        ("年化换手", f"{_fmt_num(turnover.get('annualized_turnover'))}x"),
        ("交易日占比", _fmt_pct(turnover.get("trade_day_share"))),
    ]
    exposure_html = pd.DataFrame(exposure_rows, columns=["指标", "数值"]).to_html(index=False, escape=True, classes="data-table", border=0)
    data_quality_html = _simple_rows_table(_data_quality_rows(result, metrics))
    pnl_items = _pnl_breakdown_items(result)
    pnl_table = _simple_rows_table(
        [
            (label, _fmt_money(value))
            for label, value in pnl_items
        ]
    )
    tail_html = _html_table(
        _tail_events(result),
        max_rows=10,
        percent_cols={spec.return_col, "CentralBookGrossStart", "CentralBookTurnover"},
        money_cols={"CentralBookPnL"},
    )
    contribution_html = _html_table(
        _ticker_contribution(result),
        max_rows=12,
        money_cols={"PnL", "OpenNotional", "TradeNotional", "OpenSlippageCost"},
    )
    monthly_percent_cols = {column for column in metrics.monthly_returns.columns if str(column).endswith("Return")}
    yearly_percent_cols = {column for column in metrics.yearly_returns.columns if str(column).endswith("Return")}
    monthly_html = _html_table(metrics.monthly_returns, max_rows=18, percent_cols=monthly_percent_cols)
    yearly_html = _html_table(metrics.yearly_returns, max_rows=10, percent_cols=yearly_percent_cols)
    artifact_links = "".join(
        f"<a class=\"artifact\" href=\"{html.escape(path)}\">{html.escape(name)}</a>"
        for name, path in artifacts.items()
    )
    daily_columns = [
        spec.date_col,
        "CentralBookPnL",
        "CentralBookReturn",
        "CentralBookCapitalReturn",
        "ExistingPositionPnL",
        "RebalancePnL",
        "OpenSlippageCost",
        "CentralBookGrossStart",
        "CentralBookTurnover",
        "DirectNameCoverage",
        "MissingReturnCount",
    ]
    holdings_columns = [
        "Date",
        "Ticker",
        "TargetQuantity",
        "Weight",
        "OpenNotional",
        "ExistingPositionPnL",
        "RebalancePnL",
        "OpenSlippageCost",
        "PnL",
        "HasReturn",
    ]
    comparison_payloads = list(summary.get("benchmark_comparison", {}).values())
    first_comparison = comparison_payloads[0] if comparison_payloads else {}
    data_status = "PASS" if (
        int(data_quality.get("duplicate_date_count", 0) or 0) == 0
        and int(primary.get("missing_return_count", 0) or 0) == 0
    ) else "REVIEW"
    data_status_label = "通过" if data_status == "PASS" else "需复核"
    kpis = "".join(
        [
            _kpi_card("总收益", _fmt_pct(primary.get("cumulative_return", primary.get("sum_return"))), "累计和"),
            _kpi_card("主动收益", _fmt_pct(first_comparison.get("active_sum_return")), "相对首个基准"),
            _kpi_card("Sharpe", _fmt_num(primary.get("sharpe")), "日度算术收益"),
            _kpi_card("年化波动", _fmt_pct(primary.get("annualized_volatility")), "总敞口归一化"),
            _kpi_card("最大回撤", _fmt_pct(primary.get("max_drawdown")), f"{primary.get('max_drawdown_start') or '-'} 到 {primary.get('max_drawdown_end') or '-'}"),
            _kpi_card("平均总敞口", _fmt_num(exposure.get("average_gross"), 2), "期初敞口"),
            _kpi_card("净敞口比例", _fmt_pct(exposure.get("average_net_ratio")), "平均"),
            _kpi_card("换手率", _fmt_pct(turnover.get("average_daily_turnover")), "平均日度"),
        ]
    )
    return "\n".join(
        [
            "<!doctype html>",
            "<html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
            f"<title>回测报告 - {html.escape(spec.name)}</title>",
            "<style>"
            ":root{color-scheme:light;--text:#172033;--muted:#65758b;--line:#d8e1ec;--panel:#fff;--bg:#f4f6f9;--ink:#101827;--blue:#1d4ed8;--green:#15803d;--red:#b91c1c}"
            "*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Segoe UI,Arial,sans-serif;font-size:13px;line-height:1.45}"
            "header{background:#111827;color:#fff;padding:26px 34px 30px;border-bottom:4px solid #334155}main{max-width:1280px;margin:0 auto;padding:22px 24px 42px}"
            "h1{font-size:24px;margin:0 0 10px;font-weight:650;letter-spacing:0}h2{font-size:15px;margin:0 0 12px;font-weight:650}h3{font-size:12px;margin:14px 0 8px;color:#334155;text-transform:uppercase;letter-spacing:.04em}p{margin:6px 0}.muted{color:var(--muted)}"
            ".meta{display:flex;flex-wrap:wrap;gap:9px 20px;color:#dbeafe}.meta span{white-space:nowrap}.header-row{display:flex;justify-content:space-between;gap:18px;align-items:flex-start}.badges{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}.badge{border:1px solid rgba(255,255,255,.22);border-radius:999px;padding:5px 9px;color:#e2e8f0;font-size:12px}.badge-pass{background:rgba(21,128,61,.28)}.badge-review{background:rgba(185,28,28,.24)}"
            ".grid{display:grid;gap:14px}.kpis{grid-template-columns:repeat(8,minmax(0,1fr));margin-top:-16px}.kpi{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:13px 12px;box-shadow:0 1px 2px rgba(15,23,42,.04)}"
            ".kpi-label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}.kpi-value{font-size:20px;font-weight:650;margin-top:3px;color:#0f172a}.kpi-detail{font-size:11px;color:var(--muted);min-height:16px}"
            ".section{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:17px;margin-top:14px;overflow:hidden}.two{grid-template-columns:1.35fr .85fr}.three{grid-template-columns:1fr 1fr 1fr}.readout{margin:0;padding-left:18px}.readout li{margin:5px 0}"
            ".chart{width:100%;height:auto;display:block}.bar-chart{width:100%;height:auto;display:block}.chart-wrap{width:100%;overflow:hidden}.axis-label{font-size:11px;fill:#64748b}.bar-label,.bar-value{font-size:12px;fill:#334155}.legend{display:flex;flex-wrap:wrap;gap:12px;margin-top:8px}.legend-item{display:inline-flex;align-items:center;gap:6px;color:#334155;font-size:12px}.legend-swatch{display:inline-block;width:10px;height:10px;border-radius:2px}"
            ".data-table{border-collapse:collapse;width:100%;font-size:12.5px}.data-table th{background:#eef2f7;color:#334155;text-align:right;font-weight:650}.data-table th:first-child,.data-table td:first-child{text-align:left}.data-table td{border-top:1px solid #e2e8f0;text-align:right}.data-table th,.data-table td{padding:7px 9px;white-space:nowrap}"
            ".table-scroll{overflow:auto}.artifacts{display:flex;flex-wrap:wrap;gap:8px}.artifact{color:#0f172a;text-decoration:none;border:1px solid var(--line);background:#fff;padding:7px 10px;border-radius:6px}.artifact:hover{border-color:#94a3b8}"
            "@media(max-width:1100px){.kpis{grid-template-columns:repeat(4,minmax(0,1fr))}.two,.three{grid-template-columns:1fr}.header-row{display:block}.badges{justify-content:flex-start;margin-top:12px}}@media(max-width:760px){.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}header{padding:22px 18px}main{padding:18px 12px}}"
            "</style>",
            "</head><body>",
            "<header>",
            "<div class=\"header-row\"><div>",
            f"<h1>{html.escape(spec.name)}</h1>",
            "<div class=\"meta\">"
            f"<span>Variant：<strong>{html.escape(spec.variant)}</strong></span>"
            f"<span>生成时间：<strong>{html.escape(generated_utc)}</strong></span>"
            f"<span>日期范围：<strong>{html.escape(str(data_quality.get('start_date') or '-'))} 到 {html.escape(str(data_quality.get('end_date') or '-'))}</strong></span>"
            f"<span>主收益列：<strong>{html.escape(spec.return_col)}</strong></span>"
            "</div>",
            "</div><div class=\"badges\">"
            f"<span class=\"badge {'badge-pass' if data_status == 'PASS' else 'badge-review'}\">数据{html.escape(data_status_label)}</span>"
            "<span class=\"badge\">收益：PnL / 总敞口</span>"
            "<span class=\"badge\">总收益：累计和</span>"
            "</div></div>",
            "</header>",
            "<main>",
            f"<section class=\"grid kpis\">{kpis}</section>",
            "<section class=\"grid two\"><div class=\"section\"><h2>投资结论</h2>",
            _readout_items(result, metrics),
            "</div><div class=\"section\"><h2>数据质量</h2>",
            data_quality_html,
            "</div></section>",
            "<section class=\"section\"><h2>累计收益 vs 基准</h2>",
            _return_curve_chart(result),
            "</section>",
            "<section class=\"grid two\"><div class=\"section\"><h2>回撤路径</h2>",
            _drawdown_chart(metrics),
            "</div><div class=\"section\"><h2>风险摘要</h2>",
            primary_table,
            "</div></section>",
            "<section class=\"grid two\"><div class=\"section\"><h2>PnL 归因</h2>",
            _bar_chart_svg(pnl_items, title="PnL 归因", value_type="money"),
            "</div><div class=\"section\"><h2>PnL 组成</h2>",
            pnl_table,
            "</div></section>",
            "<section class=\"grid two\"><div class=\"section\"><h2>敞口画像</h2>",
            _exposure_chart(result),
            "</div><div class=\"section\"><h2>换手路径</h2>",
            _turnover_chart(result),
            "</div></section>",
            "<section class=\"grid two\"><div class=\"section\"><h2>基准比较</h2>",
            comparison_html,
            "</div><div class=\"section\"><h2>敞口与换手</h2>",
            exposure_html,
            "</div></section>",
            "<section class=\"grid two\"><div class=\"section\"><h2>极端交易日</h2><div class=\"table-scroll\">",
            tail_html,
            "</div></div><div class=\"section\"><h2>滚动风险</h2>",
            _rolling_sharpe_chart(metrics),
            "</div></section>",
            "<section class=\"grid two\"><div class=\"section\"><h2>Ticker 贡献</h2><div class=\"table-scroll\">",
            contribution_html,
            "</div></div><div class=\"section\"><h2>分期收益</h2>",
            "<h3>月度</h3><div class=\"table-scroll\">",
            monthly_html,
            "</div><h3>年度</h3><div class=\"table-scroll\">",
            yearly_html,
            "</div></div></section>",
            "<section class=\"section\"><h2>日度明细</h2><div class=\"table-scroll\">",
            _html_table(
                result.daily,
                columns=daily_columns,
                max_rows=14,
                percent_cols={
                    spec.return_col,
                    "CentralBookCapitalReturn",
                    "CentralBookGrossStart",
                    "CentralBookTurnover",
                    "DirectNameCoverage",
                },
                money_cols={"CentralBookPnL", "ExistingPositionPnL", "RebalancePnL", "OpenSlippageCost"},
            ),
            "</div></section>",
            "<section class=\"section\"><h2>持仓明细</h2><div class=\"table-scroll\">",
            _html_table(
                result.holdings,
                columns=holdings_columns,
                max_rows=14,
                percent_cols={"Weight"},
                money_cols={"OpenNotional", "PnL", "ExistingPositionPnL", "RebalancePnL", "OpenSlippageCost"},
            ),
            "</div></section>",
            "<section class=\"section\"><h2>产物</h2><div class=\"artifacts\">",
            artifact_links or "<p class=\"muted\">无产物。</p>",
            "</div></section>",
            "</main>",
            "</body></html>",
        ]
    )


def write_standard_report(
    raw_result: BacktestResult | dict[str, Any],
    output_dir: Path | str,
    *,
    metrics: StandardMetrics | None = None,
) -> dict[str, str]:
    """写出标准报告产物包，并返回产物名称到路径的映射。"""

    result = normalize_backtest_result(raw_result)
    metrics = metrics or compute_standard_metrics(result)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    generated_utc = _utc_now()
    artifacts: dict[str, str] = {}

    def write_frame(name: str, frame: pd.DataFrame) -> None:
        if frame is None or frame.empty:
            return
        path = out / f"{_safe_name(name)}.csv"
        frame.to_csv(path, index=False, encoding="utf-8-sig")
        artifacts[name] = path.name

    write_frame("daily", result.daily)
    write_frame("decisions", result.decisions)
    write_frame("holdings", result.holdings)
    write_frame("trades", result.trades)
    for name, frame in result.tables.items():
        write_frame(name, frame)
    write_frame("metrics", metrics.metric_table)
    write_frame("monthly_returns", metrics.monthly_returns)
    write_frame("yearly_returns", metrics.yearly_returns)
    write_frame("drawdowns", metrics.drawdowns)
    write_frame("rolling_metrics", metrics.rolling_metrics)

    artifacts["summary"] = "summary.json"
    artifacts["report_md"] = "report.md"
    artifacts["report_html"] = "report.html"
    artifacts["manifest"] = "manifest.json"

    summary_payload = {
        "generated_utc": generated_utc,
        "spec": asdict(result.spec),
        "source_summary": result.summary,
        "metrics": metrics.summary,
        "artifacts": artifacts,
    }
    summary_path = out / "summary.json"
    summary_path.write_text(json.dumps(_to_jsonable(summary_payload), ensure_ascii=False, indent=2), encoding="utf-8")

    report_md = render_markdown_report(result, metrics, generated_utc=generated_utc, artifacts=artifacts)
    report_md_path = out / "report.md"
    report_md_path.write_text(report_md, encoding="utf-8")

    report_html_path = out / "report.html"
    report_html_path.write_text(
        render_html_report(result, metrics, generated_utc=generated_utc, artifacts=artifacts),
        encoding="utf-8",
    )

    manifest = {
        "generated_utc": generated_utc,
        "framework": "central_bt",
        "spec": asdict(result.spec),
        "artifacts": artifacts,
    }
    manifest_path = out / "manifest.json"
    manifest_path.write_text(json.dumps(_to_jsonable(manifest), ensure_ascii=False, indent=2), encoding="utf-8")
    return artifacts

