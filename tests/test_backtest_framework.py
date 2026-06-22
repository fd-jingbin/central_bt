from __future__ import annotations

import json
from pathlib import Path
import shutil
import uuid

import numpy as np
import pandas as pd

from central_bt.metrics import compute_standard_metrics
from central_bt.position_inputs import (
    PositionInputSpec,
    normalize_position_frame,
    positions_from_trade_frame,
    run_backtest_from_position_input,
)
from central_bt.reports import write_standard_report
from central_bt.schema import BacktestResult, BacktestSpec, normalize_backtest_result


_TEST_ROOT = Path.cwd() / "output" / "test_artifacts" / "backtest_framework"


def _scratch_dir(name: str) -> Path:
    path = _TEST_ROOT / f"{name}_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sample_daily(periods: int = 130) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=periods, freq="B")
    index = np.arange(periods, dtype=float)
    central = 0.001 + 0.006 * np.sin(index / 7.0)
    if periods > 5:
        central[5] = -0.025
    if periods > 37:
        central[37] = -0.018
    all_fund = 0.0005 + 0.004 * np.sin(index / 8.0)
    signal = 0.0006 + 0.005 * np.sin(index / 6.0)
    return pd.DataFrame(
        {
            "Date": dates,
            "CentralBookReturn": central,
            "AllFundReturn": all_fund,
            "SignalFundReturn": signal,
            "CentralBookGrossStart": 100_000_000.0 + 5_000_000.0 * np.cos(index / 9.0),
            "LongGrossStart": 62_000_000.0,
            "ShortGrossStart": 38_000_000.0,
            "NetGrossStart": 24_000_000.0,
            "NetRatioStart": 0.24,
            "CentralBookTurnover": np.where(index % 10 == 0, 0.12, 0.01),
            "Names": 24,
            "LongLegReturn": central + 0.001,
            "ShortLegReturn": -0.5 * central,
            "SelectionReturn": 0.5 * central,
            "NetTimingReturn": 0.5 * central,
            "DirectNameCoverage": 0.91,
            "CoveredNameShare": 0.98,
        }
    )


def _sample_result() -> BacktestResult:
    return BacktestResult(
        spec=BacktestSpec(
            name="unit_standard_backtest",
            variant="candidate_v1",
            research_owner="unit",
            hypothesis="Synthetic strategy should produce a complete standard report.",
        ),
        daily=_sample_daily(),
        summary={"LegacyMetric": 123},
        decisions=pd.DataFrame({"DecisionDate": ["2025-01-15"], "Variant": ["candidate_v1"]}),
        holdings=pd.DataFrame({"Date": ["2025-01-15"], "Ticker": ["AAA"], "TargetNotional": [1_000_000.0]}),
    )


def test_standard_metrics_include_performance_risk_benchmark_and_exposure() -> None:
    result = normalize_backtest_result(_sample_result())

    metrics = compute_standard_metrics(result)
    summary = metrics.summary

    assert summary["primary"]["observation_count"] == 130
    assert "sharpe" in summary["primary"]
    assert "sortino" in summary["primary"]
    assert summary["primary"]["max_drawdown"] <= 0.0
    assert "var_95" in summary["primary"]
    assert "cvar_95" in summary["primary"]
    assert "AllFundReturn" in summary["benchmark_comparison"]
    assert "information_ratio" in summary["benchmark_comparison"]["AllFundReturn"]
    assert summary["turnover"]["annualized_turnover"] > 0.0
    assert summary["exposure"]["average_gross"] > 0.0
    assert "LongLegReturn" in summary["legs"]
    assert not metrics.metric_table.empty
    assert not metrics.monthly_returns.empty
    assert not metrics.yearly_returns.empty
    assert not metrics.drawdowns.empty
    assert not metrics.rolling_metrics.empty


def test_max_drawdown_includes_first_day_loss_from_initial_equity() -> None:
    result = BacktestResult(
        spec=BacktestSpec(name="first_day_loss", return_col="Return"),
        daily=pd.DataFrame(
            {
                "Date": pd.date_range("2025-01-01", periods=3, freq="B"),
                "Return": [-0.10, 0.02, 0.01],
            }
        ),
    )

    metrics = compute_standard_metrics(normalize_backtest_result(result))

    assert abs(metrics.summary["primary"]["max_drawdown"] + 0.10) < 1e-12


def test_standard_metrics_use_cumulative_sum_not_compounding() -> None:
    result = BacktestResult(
        spec=BacktestSpec(name="arithmetic_returns", return_col="Return", periods_per_year=2),
        daily=pd.DataFrame(
            {
                "Date": pd.date_range("2025-01-01", periods=2, freq="B"),
                "Return": [0.10, 0.10],
            }
        ),
    )

    metrics = compute_standard_metrics(normalize_backtest_result(result))

    assert abs(metrics.summary["primary"]["cumulative_return"] - 0.20) < 1e-12
    assert abs(metrics.summary["primary"]["annualized_return"] - 0.20) < 1e-12
    assert list(metrics.yearly_returns["Return"].round(6)) == [0.20]


def test_write_standard_report_outputs_stable_artifact_bundle() -> None:
    result = normalize_backtest_result(_sample_result())
    output_dir = _scratch_dir("report")

    try:
        artifacts = write_standard_report(result, output_dir)

        expected = {
            "daily.csv",
            "decisions.csv",
            "holdings.csv",
            "metrics.csv",
            "monthly_returns.csv",
            "yearly_returns.csv",
            "drawdowns.csv",
            "rolling_metrics.csv",
            "summary.json",
            "report.md",
            "report.html",
            "manifest.json",
        }
        assert expected.issubset({path.name for path in output_dir.iterdir()})
        assert artifacts["summary"] == "summary.json"
        payload = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
        assert payload["spec"]["name"] == "unit_standard_backtest"
        assert payload["spec"]["variant"] == "candidate_v1"
        assert payload["source_summary"]["LegacyMetric"] == 123
        assert "primary" in payload["metrics"]
        assert "标准回测报告" in (output_dir / "report.md").read_text(encoding="utf-8")
        html_report = (output_dir / "report.html").read_text(encoding="utf-8")
        assert "累计收益 vs 基准" in html_report
        assert "日度明细" in html_report
        assert "daily.csv" in html_report
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


def test_normalize_existing_central_book_result_shape_preserves_tables() -> None:
    raw = {
        "name": "legacy",
        "daily": _sample_daily(20),
        "summary": {"DecisionCount": 2},
        "decisions": pd.DataFrame({"DecisionDate": ["2025-01-15"]}),
        "holdings_history": pd.DataFrame({"Date": ["2025-01-15"], "Ticker": ["AAA"]}),
        "timing_history": pd.DataFrame({"DecisionDate": ["2025-01-15"], "Score": [1.0]}),
        "current_snapshot": {
            "target_portfolio": pd.DataFrame({"Ticker": ["AAA"], "TargetNotional": [1_000_000.0]}),
        },
    }

    result = normalize_backtest_result(raw, spec=BacktestSpec(name="legacy_standardized"))

    assert result.spec.name == "legacy_standardized"
    assert result.spec.return_col == "CentralBookReturn"
    assert result.spec.benchmark_return_cols == ("AllFundReturn", "SignalFundReturn")
    assert result.summary["DecisionCount"] == 2
    assert not result.decisions.empty
    assert not result.holdings.empty
    assert "timing_history" in result.tables
    assert "current_target_portfolio" in result.tables


def test_position_input_backtest_uses_research_supplied_daily_positions() -> None:
    positions = pd.DataFrame(
        [
            {"Date": "2025-01-01", "Ticker": "AAA", "Weight": 0.60},
            {"Date": "2025-01-01", "Ticker": "BBB", "Weight": -0.40},
            {"Date": "2025-01-02", "Ticker": "AAA", "Weight": 0.50},
            {"Date": "2025-01-02", "Ticker": "CCC", "Weight": 0.25},
        ]
    )
    returns = pd.DataFrame(
        [
            {"Date": "2025-01-01", "Ticker": "AAA", "Open": 100.0, "Close": 110.0},
            {"Date": "2025-01-01", "Ticker": "BBB", "Open": 100.0, "Close": 95.0},
            {"Date": "2025-01-02", "Ticker": "AAA", "Open": 100.0, "Close": 102.0},
            {"Date": "2025-01-02", "Ticker": "CCC", "Open": 100.0, "Close": 104.0},
        ]
    )

    output = run_backtest_from_position_input(
        positions=positions,
        returns=returns,
        spec=BacktestSpec(name="daily_position_input"),
    )

    daily = output.result.daily
    assert list(daily["CentralBookCapitalReturn"].round(6)) == [0.08, 0.02]
    assert list(daily["CentralBookReturn"].round(6)) == [0.08, 0.026667]
    assert list(daily["CentralBookGrossStart"].round(6)) == [1.0, 0.75]
    assert list(daily["Names"]) == [2, 2]
    assert pd.isna(daily.iloc[0]["CentralBookTurnover"])
    assert round(float(daily.iloc[1]["CentralBookTurnover"]), 6) == round(0.5 * (0.10 + 0.40 + 0.25) / 0.75, 6)
    assert output.metrics.summary["primary"]["observation_count"] == 2


def test_target_trade_input_carries_targets_between_trade_dates() -> None:
    targets = pd.DataFrame(
        [
            {"Date": "2025-01-01", "Ticker": "AAA", "TargetWeight": 0.50},
            {"Date": "2025-01-03", "Ticker": "BBB", "TargetWeight": -0.25},
        ]
    )
    returns = pd.DataFrame(
        [
            {"Date": "2025-01-01", "Ticker": "AAA", "Open": 100.0, "Close": 101.0},
            {"Date": "2025-01-02", "Ticker": "AAA", "Open": 100.0, "Close": 102.0},
            {"Date": "2025-01-03", "Ticker": "AAA", "Open": 100.0, "Close": 103.0},
            {"Date": "2025-01-03", "Ticker": "BBB", "Open": 100.0, "Close": 96.0},
        ]
    )
    spec = PositionInputSpec(mode="target_trades", replace_book_on_trade_date=True)

    carried = positions_from_trade_frame(targets, returns, spec)

    assert carried.to_dict("records") == [
        {"Date": pd.Timestamp("2025-01-01"), "Ticker": "AAA", "Weight": 0.50},
        {"Date": pd.Timestamp("2025-01-02"), "Ticker": "AAA", "Weight": 0.50},
        {"Date": pd.Timestamp("2025-01-03"), "Ticker": "BBB", "Weight": -0.25},
    ]

    output = run_backtest_from_position_input(
        positions=targets,
        returns=returns,
        spec=BacktestSpec(name="target_trade_input"),
        input_spec=spec,
    )

    assert list(output.result.daily["CentralBookCapitalReturn"].round(6)) == [0.005, 0.01, 0.01]
    assert list(output.result.daily["CentralBookReturn"].round(6)) == [0.01, 0.02, 0.04]
    assert "input_positions" in output.result.tables


def test_position_input_supports_notional_with_capital_base_and_report_output() -> None:
    positions = pd.DataFrame(
        [
            {"Date": "2025-01-01", "Ticker": "AAA", "TargetNotional": 50_000_000.0},
            {"Date": "2025-01-01", "Ticker": "BBB", "TargetNotional": -25_000_000.0},
        ]
    )
    returns = pd.DataFrame(
        [
            {"Date": "2025-01-01", "Ticker": "AAA", "Open": 100.0, "Close": 102.0},
            {"Date": "2025-01-01", "Ticker": "BBB", "Open": 100.0, "Close": 96.0},
        ]
    )
    output_dir = _scratch_dir("position_input_report")
    try:
        normalized = normalize_position_frame(positions, PositionInputSpec(capital_base=100_000_000.0))
        assert normalized.to_dict("records") == [
            {"Date": pd.Timestamp("2025-01-01"), "Ticker": "AAA", "Weight": 0.5},
            {"Date": pd.Timestamp("2025-01-01"), "Ticker": "BBB", "Weight": -0.25},
        ]

        output = run_backtest_from_position_input(
            positions=positions,
            returns=returns,
            spec=BacktestSpec(name="notional_position_input"),
            input_spec=PositionInputSpec(capital_base=100_000_000.0),
            output_dir=output_dir,
        )

        assert abs(float(output.result.daily.iloc[0]["CentralBookCapitalReturn"]) - 0.02) < 1e-12
        assert round(float(output.result.daily.iloc[0]["CentralBookReturn"]), 6) == 0.026667
        assert (output_dir / "report.md").exists()
        assert (output_dir / "input_positions.csv").exists()
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


def test_position_input_supports_target_quantity_with_start_price() -> None:
    positions = pd.DataFrame(
        [
            {"Date": "2025-01-01", "Ticker": "AAA", "TargetQuantity": 100.0},
            {"Date": "2025-01-01", "Ticker": "BBB", "TargetQuantity": -50.0},
            {"Date": "2025-01-02", "Ticker": "AAA", "TargetQuantity": 80.0},
        ]
    )
    returns = pd.DataFrame(
        [
            {"Date": "2025-01-01", "Ticker": "AAA", "Open": 10.0, "Close": 11.0},
            {"Date": "2025-01-01", "Ticker": "BBB", "Open": 20.0, "Close": 19.0},
            {"Date": "2025-01-02", "Ticker": "AAA", "Open": 11.0, "Close": 11.22},
        ]
    )

    output = run_backtest_from_position_input(
        positions=positions,
        returns=returns,
        spec=BacktestSpec(name="quantity_position_input"),
        input_spec=PositionInputSpec(capital_base=10_000.0),
    )

    daily = output.result.daily
    assert list(daily["CentralBookGrossStart"].round(6)) == [0.20, 0.088]
    assert list(daily["CentralBookCapitalReturn"].round(6)) == [0.015, 0.00176]
    assert list(daily["CentralBookReturn"].round(6)) == [0.075, 0.02]
    normalized = normalize_backtest_result(output.result)
    assert "CentralBookCapitalReturn" not in normalized.spec.benchmark_return_cols
    assert "OvernightReturn" not in normalized.spec.benchmark_return_cols
    assert "IntradayReturn" not in normalized.spec.benchmark_return_cols


def test_quantity_change_pnl_splits_carry_and_open_rebalance_pnl() -> None:
    positions = pd.DataFrame(
        [
            {"Date": "2025-01-01", "Ticker": "AAA", "TargetQuantity": 100.0},
            {"Date": "2025-01-02", "Ticker": "AAA", "TargetQuantity": 50.0},
        ]
    )
    returns = pd.DataFrame(
        [
            {"Date": "2025-01-01", "Ticker": "AAA", "Open": 10.0, "Close": 12.0},
            {"Date": "2025-01-02", "Ticker": "AAA", "Open": 11.0, "Close": 11.55},
        ]
    )

    output = run_backtest_from_position_input(
        positions=positions,
        returns=returns,
        spec=BacktestSpec(name="quantity_open_execution"),
        input_spec=PositionInputSpec(capital_base=10_000.0, open_slippage_bps=10.0),
    )

    daily = output.result.daily
    assert abs(float(daily.iloc[0]["CentralBookCapitalReturn"]) - 0.0199) < 1e-12
    assert abs(float(daily.iloc[0]["CentralBookReturn"]) - 0.199) < 1e-12
    assert abs(float(daily.iloc[1]["ExistingPositionReturn"]) - (-0.08181818181818182)) < 1e-12
    assert abs(float(daily.iloc[1]["RebalanceReturn"]) - (-0.05)) < 1e-12
    assert abs(float(daily.iloc[1]["IntradayReturn"]) - (-0.05)) < 1e-12
    assert abs(float(daily.iloc[1]["OvernightGapReturn"]) - (-0.18181818181818182)) < 1e-12
    assert abs(float(daily.iloc[1]["OpenSlippageReturn"]) - (-0.001)) < 1e-12
    assert abs(float(daily.iloc[1]["CentralBookCapitalReturn"]) - (-0.007305)) < 1e-12
    assert abs(float(daily.iloc[1]["CentralBookReturn"]) - (-0.1328181818181818)) < 1e-12
    holdings = output.result.holdings
    second_day = holdings[holdings["Date"].eq(pd.Timestamp("2025-01-02"))].iloc[0]
    assert second_day["PreviousQuantity"] == 100.0
    assert second_day["TargetQuantity"] == 50.0
    assert second_day["DeltaQuantity"] == -50.0
    assert abs(float(second_day["ExistingPositionPnL"]) - (-45.0)) < 1e-12
    assert abs(float(second_day["RebalancePnL"]) - (-27.5)) < 1e-12

