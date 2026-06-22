# 研究方法论

`central_bt` 的研究资料按一条主线组织：假设、feature 证据、shadow variant、标准回测、ledger 决策。

这里借鉴 `C:\Dashboard\pm_dashboard\central_book` 的研究治理方式，保留它对 feature 研究、candidate 回测、scorecard 和 ledger 的要求。具体交易规则留在各研究项目里。

## 研究线状态

每个想法只放在一个状态里：

| 状态 | 含义 | 动作 |
| --- | --- | --- |
| `Idea` | 只有业务假设 | 写 `research_brief.md` |
| `FeatureDiagnostic` | 已有单 feature 或 bucket 证据 | 做诊断报告，不进组合 |
| `ShadowVariant` | 有清楚的构建规则 | 每日或定期跑 shadow |
| `ValidationCandidate` | 通过初步 replay 或 smoke | 进入多起点、多 phase 验证 |
| `ProductionCandidate` | 主要 gate 已通过 | 等 live shadow 和升级讨论 |
| `Production` | 已批准为默认版本 | 保留 registry、ledger、回滚说明 |
| `Rejected` | 证据或风险不过关 | 写失败原因，移出 active runner |
| `Archived` | 历史可复现 | 保留脚本和产物 |

状态写进 `variant_registry.csv` 或 `research_ledger.md`。失败实验也要写，后面少做重复搜索。

## 从 Idea 到候选

1. 写假设

   用一句业务语言说明经济含义。例如：“高质量 book 的持续加仓，比一次性持仓更有信息量。”

2. 写 point-in-time 规则

   每个输入字段说明决策日是否可见、延迟几天、会不会修订、缺失时怎么处理。未来收益只能做 evaluation label。

3. 建 feature catalog

   登记 feature 名称、家族、层级、方向、来源、窗口、变换、缺失规则、泄露检查和解释。

4. 做 feature 证据

   先看 bucket/lift、覆盖率、稳定性、相关性、turnover impact、单调性和极端样本。组合回测通过后，也要能回到 feature 层解释。

5. 定义 shadow variant

   每个 variant 只改少数机制。记录 parent、变更摘要、预期影响、主要风险、freedom count 和当前状态。

6. 生成标准回测输入

   runner 输出 `Date,Ticker,TargetQuantity`、`Date,Ticker,Weight` 或等价持仓目标，再交给 `central_bt`。

7. 跑 scorecard

   至少比较 anchor、candidate 和必要 benchmark。重点看最弱窗口、P25、最差回撤、换手、敞口、持仓数量、tail days 和数据质量。

8. 更新 ledger

   结论写成 `Reject`、`Shadow`、`Observe`、`ProductionCandidate` 或 `Production`。聊天记录不能承担项目记忆。

## Feature 家族

Feature 先归类，再进模型：

| 家族 | 问题 | 示例 |
| --- | --- | --- |
| `BookBehavior` | 哪些 PM/book 的行为更可信 | 加仓、减仓、持仓稳定性、交易强度、集中度纪律 |
| `OutcomeQuality` | 历史结果质量如何 | hit rate、60D return、drawdown control、样本长度 |
| `StockSupport` | 股票是否有独立且持续的支持 | support count、support quality、support persistence、action evidence |
| `ThesisQuality` | 多头 thesis 是否仍健康 | revision、target price、earnings/catalyst、内部路径质量 |
| `ThemeIndustry` | 主题和行业给了什么上下文 | theme breadth、flow、theme state、industry dominance |
| `MarketTechnical` | 价格行为是否支持入场和持有 | pullback、trend hold、extension、recent return |
| `PortfolioConstruction` | 组合层面怎么控风险和容量 | gross cap、name cap、cluster penalty、turnover |

`MarketTechnical` 更适合做入场、持有或风险 overlay。把它放进主 stock-selection 模型前，要有更强的稳定性证据。

## Feature Catalog

每条研究线放一份 `feature_catalog.csv`：

| 字段 | 说明 |
| --- | --- |
| `FeatureName` | 稳定字段名 |
| `FeatureFamily` | feature 家族 |
| `EntityLevel` | `Book`、`Ticker`、`Theme`、`Portfolio`、`Market` 等 |
| `Direction` | 越高越好、越低越好、双侧、仅解释 |
| `DataSource` | 原始数据来源 |
| `PointInTimeRule` | 决策日可见性和延迟规则 |
| `Window` | 计算窗口 |
| `Transform` | rank、z-score、winsorize、clip 等 |
| `MissingPolicy` | 缺失填 0、丢弃、继承、设为未知等 |
| `Hypothesis` | 经济解释 |
| `LeakageCheck` | 泄露检查方法 |
| `EvidencePath` | 单 feature 证据路径 |
| `Status` | diagnostic、shadow、production、rejected |

进入 production scoring 的 feature 要有 catalog 记录。只用于报告或 watchlist 的 feature，也标成 `diagnostic`。

## Feature 入库检查

新 feature 进模型前，先过这些检查：

- 假设能用业务语言解释。
- 决策日可见，没有未来函数。
- 没有 hardcode ticker、book、PM、日期、行业、国家、事件或某次 drawdown。
- point-in-time 可用性已验证。
- 覆盖率足够，缺失规则合理。
- 单 feature 或 bucket 证据有记录。
- 结果覆盖多个历史阶段和多个起点。
- 对 turnover、gross、name count、drawdown 的影响能解释。
- 与已有 feature 的重复度已检查。
- CIO 或 PM 能理解它为什么会影响组合。

对监控有用、交易证据不足的 feature，放进报告或 watchlist。

## Variant Registry

每条研究线维护 `variant_registry.csv` 或 `variant_registry.md`：

| 字段 | 说明 |
| --- | --- |
| `Variant` | variant 全名 |
| `ShortName` | 可读短名 |
| `ParentVariant` | 对照基线 |
| `Status` | 当前状态 |
| `Mechanism` | 改了什么机制 |
| `FeatureFamiliesChanged` | 涉及哪些 feature 家族 |
| `FreedomCount` | 新增自由度数量，越低越好 |
| `ExpectedImpact` | 预期改善收益、回撤、换手、持有期等 |
| `MainRisk` | 最可能失败的方式 |
| `Owner` | 负责人 |
| `CreatedDate` | 创建日期 |
| `LatestDecision` | 最新结论 |
| `ArtifactPath` | scorecard、report、ledger 路径 |

Active registry 只放当前真实候选。历史和失败 variant 可以复现，但不要留在默认 runner 或 active order 里。

## 回测口径

`central_bt` 的标准回测口径：

- 价格输入为 `Date,Ticker,Open,Close`。
- 数量变动按开盘成交。
- 未变化数量赚 close-to-close PnL。
- 变化数量赚 open-to-close 的 rebalance/intraday PnL。
- 开盘滑点只作用于变化数量。
- 当天收益为 `daily_pnl / daily_gross_exposure_start`。
- 总收益为日收益累计和，不复利。

研究可以保留自己的模拟器。进入同一套比较时，输出标准 `daily.csv`、`holdings.csv`、`metrics.csv`、`summary.json`、`report.md` 和 `report.html`。

## 验证 Gate

1. `Feature Evidence`

   单 feature、bucket、coverage、稳定性和解释性检查。通过后再做组合 candidate。

2. `Cheap Replay`

   如果变化只影响构建、持有、加减仓或 sizing，且使用同一份 point-in-time snapshot，可以先做快速 replay。Replay 用来筛选 finalist。

3. `Exact Smoke`

   对少数 finalist 做 live-like 或 full-engine 短窗口验证，确认实现和 PnL 口径一致。

4. `Multi-Start / Multi-Phase`

   不同 start date、不同 rebalance phase 都要跑。看 P25、min、worst drawdown 和 dispersion。

5. `Live Shadow`

   生产前观察若干个真实刷新日，确认输入、target、history carry、report 和 readiness 都稳定。

## Scorecard

标准 scorecard 至少包含：

| 字段 | 说明 |
| --- | --- |
| `Variant` | variant 名 |
| `StartDate` | 验证起点 |
| `Phase` | rebalance phase |
| `TotalReturn` | 累计和收益 |
| `P25Return` | 跨 start/phase 的 P25 收益 |
| `MinReturn` | 最弱窗口收益 |
| `Sharpe` | 风险调整收益 |
| `MaxDrawdown` | 最大回撤 |
| `WorstWeeklyDrawdown` | 最差周度回撤 |
| `AvgDailyTurnover` | 平均日换手 |
| `GrossExposure` | 平均或目标总敞口 |
| `NetExposure` | 平均或目标净敞口 |
| `NameCount` | 平均或目标持仓数量 |
| `TailDayLoss` | 极端单日损失 |
| `FeatureFamilyMix` | feature 家族占比 |
| `DataQualityFlag` | 数据质量状态 |
| `Decision` | 通过、reject、shadow、observe、production-ready |

如果 mean return 改善，但最弱窗口或最差回撤明显变差，先放 shadow。

候选可以分成几类：

- `Anchor`：当前基准或生产默认。
- `UpgradeCandidate`：收益、最弱窗口、回撤和 dispersion 都能对上 anchor。
- `CleanerShadow`：收益未必更高，但解释性、风险或 feature mix 更干净。
- `ReturnHoldout`：收益有吸引力，稳定性还没过关。
- `Watchlist`：证据不足，只保留观察。
- `Rejected`：已验证失败，不再进入 active runner。

## 切生产

切生产前，检查这些项：

- 它解决的问题写得清楚。
- 结果覆盖多个起点、多个 phase 和多个市场阶段。
- worst-case drawdown 没有明显恶化。
- turnover 增加有原因。
- feature stacking 能解释。
- point-in-time 和 exclusion 规则没有破。
- 能用一句话向 CIO 说明。
- ledger 已记录，回滚路径已写清。

生产切换要小而明确。宽参数搜索的结果先 shadow。

## Research Ledger 模板

重要实验写入 `research_ledger.md`：

```markdown
## YYYY-MM-DD - <研究名称>

目标：

- <用业务语言说明要解决的问题>

方法：

- Parent variant:
- Candidate variant:
- Feature / rule change:
- Point-in-time rule:

证据：

| Window | Variant | Runs | Mean return | P25 return | Min return | Worst DD | Turnover |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |

解读：

- <结果说明>
- <失败模式>
- <是否符合原始假设>

结论：

- Decision: Reject / Shadow / Observe / ProductionCandidate / Production
- Next gate:
- Artifact paths:
```

## 研究目录

常用目录结构：

```text
research/<candidate>/
  research_brief.md
  feature_catalog.csv
  feature_evidence.csv
  variant_registry.csv
  positions.csv
  prices.csv
  backtest/
    daily.csv
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
  scorecard.csv
  research_ledger.md
```

`central_bt` 当前负责标准 backtest bundle。`feature_catalog.csv`、`variant_registry.csv`、`scorecard.csv` 和 `research_ledger.md` 可以先由研究 runner 生成，后续再纳入自动化。
