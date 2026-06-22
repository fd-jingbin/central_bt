# 持仓输入示例

这里的 CSV 只用来说明交接格式。研究代码可以生成其中一种输入，再配一份 `Date,Ticker,Open,Close` 价格文件，交给框架生成报告。

命令都从 repo 根目录运行。第一次使用时先准备环境：

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -e .
```

## 示例 1：数量目标

输入：

```text
quantity_targets.csv
ticker_returns.csv
benchmark_returns.csv
```

运行：

```powershell
.\.venv\Scripts\python.exe -B .\scripts\run_position_input_backtest.py `
  --positions central_bt/examples/quantity_targets.csv `
  --returns central_bt/examples/ticker_returns.csv `
  --benchmark-returns central_bt/examples/benchmark_returns.csv `
  --output-dir output/examples/quantity_targets_backtest `
  --variant-name sample_quantity_targets `
  --mode positions `
  --capital-base 100000000
```

数量带方向：多头为正，空头为负。价格文件提供 `Open` 和 `Close`，框架用它把数量转成名义金额，并算 open-to-close 收益。

数量变化时：

```text
existing_position_pnl = previous_quantity * (close - previous_close)
intraday_pnl = (target_quantity - previous_quantity) * (close - open)
slippage_cost = abs(delta_quantity) * open * open_slippage_bps / 10000
```

## 示例 2：每日权重

输入：

```text
daily_positions.csv
ticker_returns.csv
benchmark_returns.csv
```

运行：

```powershell
.\.venv\Scripts\python.exe -B .\scripts\run_position_input_backtest.py `
  --positions central_bt/examples/daily_positions.csv `
  --returns central_bt/examples/ticker_returns.csv `
  --benchmark-returns central_bt/examples/benchmark_returns.csv `
  --output-dir output/examples/daily_positions_backtest `
  --variant-name sample_daily_positions `
  --mode positions
```

## 示例 3：目标交易

输入：

```text
target_trades.csv
ticker_returns.csv
benchmark_returns.csv
```

运行：

```powershell
.\.venv\Scripts\python.exe -B .\scripts\run_position_input_backtest.py `
  --positions central_bt/examples/target_trades.csv `
  --returns central_bt/examples/ticker_returns.csv `
  --benchmark-returns central_bt/examples/benchmark_returns.csv `
  --output-dir output/examples/target_trades_backtest `
  --variant-name sample_target_trades `
  --mode target_trades
```

`target_trades` 模式下，每个交易日默认是一整本目标组合。框架会把目标持有到下一次交易日。

## 示例 4：名义金额目标

输入：

```text
notional_targets.csv
ticker_returns.csv
benchmark_returns.csv
```

运行：

```powershell
.\.venv\Scripts\python.exe -B .\scripts\run_position_input_backtest.py `
  --positions central_bt/examples/notional_targets.csv `
  --returns central_bt/examples/ticker_returns.csv `
  --benchmark-returns central_bt/examples/benchmark_returns.csv `
  --output-dir output/examples/notional_targets_backtest `
  --variant-name sample_notional_targets `
  --mode positions `
  --capital-base 100000000
```

报告会写到 `--output-dir`，主要看 `report.html`、`summary.json`、`metrics.csv`、`daily.csv` 和 `holdings.csv`。
