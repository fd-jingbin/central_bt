# 标准回测框架

这份文档只讲回测接口。研究方法、feature 证据、variant 管理和升级流程看 `RESEARCH_METHODOLOGY_STANDARD.md`。

框架代码在：

```text
central_bt/
```

研究 runner 可以有自己的信号、模型、优化器和组合构建逻辑。交给 `central_bt` 时，只需要给一张持仓表和一张价格表。框架接手后，负责 PnL、收益、指标和报告。

## 持仓输入

优先用数量目标：

```text
Date,Ticker,TargetQuantity
```

`TargetQuantity` 带方向：

- 多头股票/合约为正数
- 空头股票/合约为负数
- 价格文件要有 `Open` 和 `Close`
- 框架用数量、开盘价和 multiplier 算名义金额，再换成资本权重

也可以用这些列：

```text
Date,Ticker,Weight
Date,Ticker,TargetWeight
Date,Ticker,TargetNotional
Date,Ticker,Direction,Units
```

如果输入是 `TargetQuantity`、`TargetNotional` 或 `Direction,Units`，要传 `capital_base`。框架会用它把每一行转成带方向权重。

## 价格输入

标准价格表：

```text
Date,Ticker,Open,Close
```

`Close / Open - 1` 会被当作 open-to-close ticker return。

这些列也能作为回退：

- `CloseRet`
- `TickerReturn`
- `DailyReturn`
- `Return`

回退列要代表 open-to-close return。`Open` 可以用 `StartPrice`、`Price` 或 `PrevClose` 替代。

## 数量 PnL

数量输入按开盘成交处理：

```text
previous_quantity = 前一日收盘持仓数量
target_quantity = 今日开盘交易后的目标持仓数量
delta_quantity = target_quantity - previous_quantity

existing_position_pnl = previous_quantity * (close - previous_close) * multiplier
intraday_pnl = delta_quantity * (close - open) * multiplier
slippage_cost = abs(delta_quantity) * open * multiplier * open_slippage_bps / 10000
daily_pnl = existing_position_pnl + intraday_pnl - slippage_cost
daily_gross_exposure_start = sum(abs(target_quantity * open * multiplier))
daily_return = daily_pnl / daily_gross_exposure_start
cumulative_return = daily_return.cumsum()
```

未变化的数量赚 close-to-close PnL。开盘变化的数量赚 open-to-close PnL。滑点只收在变化数量上。

`OvernightGapPnL` 只做诊断字段，不放进主归因桶。

收益不复利。当天 return 用 `daily_pnl / daily_gross_exposure_start`，总 return 用日 return 累计和。

## 输入模式

`positions`

- 输入已经是每日生效持仓。
- 框架按原样读取。

`target_trades`

- 输入是交易生效日上的目标 ticker 行。
- 框架会把目标持有到下一次交易日。
- 默认每个交易日替换整本组合。
- 如果输入只想更新出现的 ticker，打开 incremental targets。

`delta_trades`

- 输入是带方向的权重变化。
- 框架把 delta 累加成持仓。

日期代表持仓生效日。需要 T+1 执行时，在交给框架前先移动目标日期。

## 研究 runner 要交什么

每个研究运行至少交一种持仓输入和一张价格表。runner 也可以直接产出标准 bundle。

如果 runner 只写 CSV，用 CLI 生成 bundle：

```powershell
.\.venv\Scripts\python.exe -B .\scripts\run_position_input_backtest.py `
  --positions output/research/candidate/positions.csv `
  --returns output/research/candidate/returns.csv `
  --output-dir output/research/candidate/backtest `
  --variant-name candidate `
  --mode positions
```

标准 bundle：

```text
daily.csv
decisions.csv
holdings.csv
metrics.csv
monthly_returns.csv
yearly_returns.csv
drawdowns.csv
rolling_metrics.csv
summary.json
report.md
report.html
manifest.json
```

研究目录里还建议放这些文件：

```text
research_brief.md
feature_catalog.csv
feature_evidence.csv
variant_registry.csv
scorecard.csv
research_ledger.md
```

这些文件记录假设、feature、variant 状态和验证结论。标准回测比较仍以 bundle 为准。

## 日度表字段

框架至少需要：

```text
Date
CentralBookReturn
```

常用扩展字段：

```text
AllFundReturn
SignalFundReturn
CentralBookGrossStart
LongGrossStart
ShortGrossStart
NetGrossStart
NetRatioStart
CentralBookTurnover
Names
LongLegReturn
ShortLegReturn
SelectionReturn
NetTimingReturn
```

## 指标

绩效：

- 总收益
- 年化收益
- 年化波动率
- Sharpe
- Sortino
- Calmar
- 胜率
- 盈亏比

风险：

- 最大回撤和回撤日期
- 平均回撤
- VaR 95/99
- CVaR 95/99
- 偏度
- 峰度
- 最好和最差单日
- 连续盈利和连续亏损区间

基准比较：

- 主动收益
- 跟踪误差
- 信息比率
- Beta
- 年化 Alpha
- 相关性
- 上行/下行捕获

组合行为：

- 平均和最大总敞口
- 多头、空头、净敞口和净敞口比例
- 平均持仓数量
- 日换手和年化换手
- 多空腿诊断指标

## 接入新的 runner

当研究代码能产出 positions 和 returns DataFrame，直接调输入驱动 API：

```python
from central_bt import BacktestSpec, PositionInputSpec, run_backtest_from_position_input

spec = BacktestSpec(
    name="central_book",
    variant="candidate_v1",
    research_owner="analyst",
    hypothesis="说明这个候选策略正在检验的经济行为。",
)

run_backtest_from_position_input(
    positions=positions_df,
    returns=returns_df,
    spec=spec,
    input_spec=PositionInputSpec(mode="positions"),
    output_dir="output/research/candidate_v1",
)
```

已有 engine 如果只产出日度收益表，可以继续用 `StandardBacktestRunner`。

## 升级纪律

这个框架只管口径。能不能上线，要看验证。

生产候选至少要过这些检查：

- point-in-time 输入
- 多起点、多 phase
- 最弱窗口收益
- 最差回撤
- 换手和持仓数量
- 最新 target review
- 清楚的方法说明

每次升级讨论都要留下 `research_ledger.md` 或等价记录，并保留 `report.html`、`summary.json` 和 scorecard。
