from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from central_bt import BacktestSpec, PositionInputSpec, run_backtest_from_position_input


class ChineseHelpFormatter(argparse.HelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):
        super().add_usage(usage, actions, groups, prefix or "用法: ")


def _configure_text_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="读取研究侧提供的持仓/交易目标，并写出标准回测报告产物包。",
        formatter_class=ChineseHelpFormatter,
        add_help=False,
    )
    parser._optionals.title = "选项"
    parser.add_argument("-h", "--help", action="help", help="显示帮助信息并退出。")
    parser.add_argument("--positions", required=True, help="包含 Date、Ticker 以及 TargetQuantity/Weight/TargetNotional 的 CSV。")
    parser.add_argument("--returns", required=True, help="价格 CSV，包含 Date、Ticker、Open、Close；收益列只作为可选回退。")
    parser.add_argument("--benchmark-returns", default="", help="可选的日度基准收益 CSV，包含 Date 和一个或多个收益列。")
    parser.add_argument("--output-dir", default="output/position_input_backtest", help="标准报告产物的输出目录。")
    parser.add_argument("--mode", default="positions", choices=["positions", "target_trades", "delta_trades"], help="输入模式。")
    parser.add_argument("--variant-name", default="research_position_input", help="本次研究 variant 名称。")
    parser.add_argument("--owner", default="", help="研究负责人或团队。")
    parser.add_argument("--hypothesis", default="", help="本次回测检验的研究假设。")
    parser.add_argument("--weight-col", default="", help="可选：显式指定带方向权重列。")
    parser.add_argument("--notional-col", default="", help="可选：显式指定带方向名义金额列。")
    parser.add_argument("--capital-base", type=float, default=1.0, help="用于把数量/名义金额/units 转换成权重的资本基数。")
    parser.add_argument("--open-slippage-bps", type=float, default=0.0, help="对变化数量/名义金额收取的单边开盘成交滑点，单位 bps。")
    parser.add_argument(
        "--incremental-targets",
        action="store_true",
        help="用于 target_trades：每个交易日只更新出现的 tickers，而不是替换整本组合。",
    )
    return parser.parse_args()


def _resolve_path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def main() -> None:
    _configure_text_output()
    args = _parse_args()
    positions = pd.read_csv(_resolve_path(args.positions))
    returns = pd.read_csv(_resolve_path(args.returns))
    benchmark_returns = pd.read_csv(_resolve_path(args.benchmark_returns)) if str(args.benchmark_returns).strip() else None
    output_dir = _resolve_path(args.output_dir)
    output = run_backtest_from_position_input(
        positions=positions,
        returns=returns,
        benchmark_returns=benchmark_returns,
        spec=BacktestSpec(
            name="central_bt_position_input",
            variant=args.variant_name,
            research_owner=args.owner,
            hypothesis=args.hypothesis,
        ),
        input_spec=PositionInputSpec(
            mode=args.mode,
            weight_col=args.weight_col,
            notional_col=args.notional_col,
            capital_base=float(args.capital_base),
            open_slippage_bps=float(args.open_slippage_bps),
            replace_book_on_trade_date=not bool(args.incremental_targets),
        ),
        output_dir=output_dir,
    )
    print(f"position_input_backtest_output={output_dir}")
    if output.artifacts:
        print(f"position_input_backtest_report={output_dir / output.artifacts.get('report_md', 'report.md')}")


if __name__ == "__main__":
    main()
