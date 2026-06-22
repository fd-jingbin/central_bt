# central_bt

`central_bt` 给研究 runner 一个固定交接接口：研究侧交持仓和价格，框架负责算 PnL、收益、指标和报告。

适合这类场景：

- 研究代码已经能生成每日持仓、目标交易或目标数量。
- 价格数据是 `Date,Ticker,Open,Close`。
- 需要把不同 candidate 放到同一套回测口径下比较。

## 输入

数量目标：

```csv
Date,Ticker,TargetQuantity
2025-01-02,AAA US Equity,500000
2025-01-02,BBB US Equity,-600000
```

价格数据：

```csv
Date,Ticker,Open,Close
2025-01-02,AAA US Equity,100.00,101.20
2025-01-02,BBB US Equity,50.00,49.10
```

数量输入按开盘成交算 PnL：

```text
existing_position_pnl = previous_quantity * (close - previous_close) * multiplier
intraday_pnl = (target_quantity - previous_quantity) * (close - open) * multiplier
slippage_cost = abs(delta_quantity) * open * multiplier * open_slippage_bps / 10000
daily_gross_exposure_start = sum(abs(target_quantity * open * multiplier))
daily_return = (existing_position_pnl + intraday_pnl - slippage_cost) / daily_gross_exposure_start
cumulative_return = daily_return.cumsum()
```

收益不复利。当天 return 用 `daily pnl / daily gross exposure start`，总 return 用日 return 累计和。

## 跑一个示例

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -B .\scripts\run_position_input_backtest.py `
  --positions .\central_bt\examples\quantity_targets.csv `
  --returns .\central_bt\examples\ticker_returns.csv `
  --benchmark-returns .\central_bt\examples\benchmark_returns.csv `
  --output-dir .\output\examples\quantity_targets_backtest `
  --variant-name sample_quantity_targets `
  --mode positions `
  --capital-base 100000000 `
  --open-slippage-bps 5
```

输出目录里会有 `daily.csv`、`holdings.csv`、`metrics.csv`、`summary.json`、`report.md` 和 `report.html`。

## 文档

- `docs/STANDARD_BACKTEST_FRAMEWORK.md`：输入格式、PnL 口径、产物清单。
- `docs/RESEARCH_METHODOLOGY_STANDARD.md`：feature、variant、scorecard、ledger 和升级流程。
