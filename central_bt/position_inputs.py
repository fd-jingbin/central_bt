from __future__ import annotations

"""输入驱动的回测 runner。

研究代码可以自由构建信号。标准框架只需要持仓或交易目标 DataFrame，以及 ticker 级价格/收益数据。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from central_bt.metrics import compute_standard_metrics
from central_bt.reports import write_standard_report
from central_bt.runner import StandardRunOutput
from central_bt.schema import BacktestResult, BacktestSpec


EPS = 1e-12


@dataclass(frozen=True)
class PositionInputSpec:
    """持仓驱动研究回测的列契约。

    推荐的 live-like 输入是一行代表一个生效持仓：

    ``Date, Ticker, TargetQuantity``

    数量带方向：多头为正，空头为负。收益/价格数据必须提供 ``Open`` 和 ``Close``，
    这样框架才能把数量转换为名义金额，并推导 open-to-close 收益。``Weight`` 仍可作为研究侧已经标准化的快捷输入。
    """

    mode: str = "positions"
    date_col: str = "Date"
    ticker_col: str = "Ticker"
    quantity_col: str = "TargetQuantity"
    weight_col: str = ""
    notional_col: str = ""
    price_col: str = "Open"
    close_col: str = "Close"
    direction_col: str = "Direction"
    units_col: str = "Units"
    unit_notional_col: str = "UnitNotional"
    contract_multiplier_col: str = "ContractMultiplier"
    capital_base_col: str = "CapitalBase"
    default_unit_notional: float = 1.0
    default_contract_multiplier: float = 1.0
    capital_base: float = 1.0
    open_slippage_bps: float = 0.0
    replace_book_on_trade_date: bool = True
    missing_return_policy: str = "zero"


def _coerce_mode(mode: str) -> str:
    value = str(mode or "positions").strip().lower()
    aliases = {
        "position": "positions",
        "daily_positions": "positions",
        "target": "target_trades",
        "targets": "target_trades",
        "target_trade": "target_trades",
        "target_trades": "target_trades",
        "delta": "delta_trades",
        "delta_trade": "delta_trades",
        "delta_trades": "delta_trades",
    }
    value = aliases.get(value, value)
    if value not in {"positions", "target_trades", "delta_trades"}:
        raise ValueError(f"Unsupported position input mode: {mode}")
    return value


def _first_existing(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    for column in candidates:
        if column and column in frame.columns:
            return column
    return None


def _numeric(series: Any) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _normalize_ticker(value: Any) -> str:
    return str(value).strip().upper()


def _safe_pnl_return(pnl: float, gross_exposure: float) -> float:
    if abs(float(gross_exposure)) <= EPS:
        return 0.0 if abs(float(pnl)) <= EPS else float("nan")
    return float(pnl) / float(gross_exposure)


def _capital_base_series(frame: pd.DataFrame, spec: PositionInputSpec) -> pd.Series:
    if spec.capital_base_col in frame.columns:
        series = _numeric(frame[spec.capital_base_col])
        fallback = float(spec.capital_base)
        if fallback > EPS:
            series = series.fillna(fallback)
        return series
    return pd.Series(float(spec.capital_base), index=frame.index, dtype=float)


def _signed_weight(frame: pd.DataFrame, spec: PositionInputSpec) -> pd.Series:
    weight_col = _first_existing(
        frame,
        (
            spec.weight_col,
            "Weight",
            "TargetWeight",
            "SignedWeight",
            "PortfolioWeight",
        ),
    )
    if weight_col is not None:
        return _numeric(frame[weight_col]).fillna(0.0).astype(float)

    notional_col = _first_existing(
        frame,
        (
            spec.notional_col,
            "TargetNotional",
            "Notional",
            "MarketValue",
            "PositionNotional",
        ),
    )
    if notional_col is not None:
        capital = _capital_base_series(frame, spec)
        if capital.abs().le(EPS).any():
            raise ValueError("Notional input requires positive capital_base or CapitalBase values.")
        return (_numeric(frame[notional_col]).fillna(0.0).astype(float) / capital.astype(float)).astype(float)

    quantity_col = _first_existing(
        frame,
        (
            spec.quantity_col,
            "TargetQuantity",
            "Quantity",
            "Shares",
            "TargetShares",
        ),
    )
    if quantity_col is not None:
        price_col = _first_existing(
            frame,
            (
                spec.price_col,
                "OpenPrice",
                "StartPrice",
                "Price",
                "Open",
                "PrevClose",
            ),
        )
        if price_col is None:
            raise ValueError(
                "Quantity input requires StartPrice/Price/Open/PrevClose on the position rows "
                "or in the ticker returns frame."
            )
        quantity = _numeric(frame[quantity_col]).fillna(0.0).astype(float)
        price = _numeric(frame[price_col]).fillna(0.0).astype(float)
        if spec.contract_multiplier_col in frame.columns:
            multiplier = _numeric(frame[spec.contract_multiplier_col]).fillna(float(spec.default_contract_multiplier)).astype(float)
        else:
            multiplier = pd.Series(float(spec.default_contract_multiplier), index=frame.index, dtype=float)
        capital = _capital_base_series(frame, spec)
        if capital.abs().le(EPS).any():
            raise ValueError("Quantity input requires positive capital_base or CapitalBase values.")
        return (quantity * price * multiplier / capital).astype(float)

    if spec.direction_col in frame.columns and spec.units_col in frame.columns:
        direction = _numeric(frame[spec.direction_col]).fillna(0.0).astype(float)
        units = _numeric(frame[spec.units_col]).fillna(0.0).astype(float)
        if spec.unit_notional_col in frame.columns:
            unit_notional = _numeric(frame[spec.unit_notional_col]).fillna(float(spec.default_unit_notional)).astype(float)
        else:
            unit_notional = pd.Series(float(spec.default_unit_notional), index=frame.index, dtype=float)
        capital = _capital_base_series(frame, spec)
        if capital.abs().le(EPS).any():
            raise ValueError("Direction/Units input requires positive capital_base or CapitalBase values.")
        return (np.sign(direction) * units.abs() * unit_notional / capital).astype(float)

    raise ValueError(
        "Position input must include one of Weight/TargetWeight, TargetNotional, "
        "or Direction + Units columns."
    )


def normalize_position_frame(
    positions: pd.DataFrame,
    spec: PositionInputSpec | None = None,
    returns: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """把研究持仓标准化为 ``Date, Ticker, Weight``。"""

    cfg = spec or PositionInputSpec()
    if positions is None or positions.empty:
        raise ValueError("Position input is empty.")
    if cfg.date_col not in positions.columns:
        raise ValueError(f"Position input is missing date column: {cfg.date_col}")
    if cfg.ticker_col not in positions.columns:
        raise ValueError(f"Position input is missing ticker column: {cfg.ticker_col}")
    work = positions.copy()
    work["Date"] = pd.to_datetime(work[cfg.date_col], errors="coerce").dt.normalize()
    work["Ticker"] = work[cfg.ticker_col].map(_normalize_ticker)
    if returns is not None and not returns.empty:
        price_columns = [
            column
            for column in ("OpenPrice", "StartPrice", "Close", cfg.contract_multiplier_col)
            if column in returns.columns and column not in work.columns
        ]
        if price_columns:
            work = work.merge(
                returns[["Date", "Ticker", *price_columns]].drop_duplicates(["Date", "Ticker"], keep="last"),
                on=["Date", "Ticker"],
                how="left",
            )
    work["Weight"] = _signed_weight(work, cfg)
    quantity_col = _first_existing(
        work,
        (
            cfg.quantity_col,
            "TargetQuantity",
            "Quantity",
            "Shares",
            "TargetShares",
        ),
    )
    if quantity_col is not None:
        work["TargetQuantity"] = _numeric(work[quantity_col]).fillna(0.0).astype(float)
    work = work.dropna(subset=["Date"])
    work = work[work["Ticker"].ne("")]
    work = work[np.isfinite(pd.to_numeric(work["Weight"], errors="coerce").fillna(0.0))]
    keep_cols = ["Date", "Ticker", "Weight"]
    if "TargetQuantity" in work.columns:
        keep_cols.append("TargetQuantity")
    work = work.loc[work["Weight"].abs().gt(EPS), keep_cols]
    if work.empty:
        return pd.DataFrame(columns=keep_cols)
    agg = {"Weight": "sum"}
    if "TargetQuantity" in work.columns:
        agg["TargetQuantity"] = "sum"
    return work.groupby(["Date", "Ticker"], as_index=False, sort=True).agg(agg).loc[
        lambda frame: frame["Weight"].abs().gt(EPS)
    ].reset_index(drop=True)


def normalize_return_frame(
    returns: pd.DataFrame,
    *,
    date_col: str = "Date",
    ticker_col: str = "Ticker",
    return_col: str = "",
    price_col: str = "",
    close_col: str = "",
) -> pd.DataFrame:
    """把 ticker 级价格数据标准化为 ``Date, Ticker, TickerReturn``。"""

    if returns is None or returns.empty:
        raise ValueError("Return input is empty.")
    if date_col not in returns.columns:
        raise ValueError(f"Return input is missing date column: {date_col}")
    if ticker_col not in returns.columns:
        raise ValueError(f"Return input is missing ticker column: {ticker_col}")
    selected_return_col = _first_existing(
        returns,
        (
            return_col,
            "Return",
            "TickerReturn",
            "CloseRet",
            "DailyReturn",
        ),
    )
    work = returns.copy()
    work["Date"] = pd.to_datetime(work[date_col], errors="coerce").dt.normalize()
    work["Ticker"] = work[ticker_col].map(_normalize_ticker)
    selected_price_col = _first_existing(
        work,
        (
            price_col,
            "OpenPrice",
            "StartPrice",
            "Price",
            "Open",
            "PrevClose",
        ),
    )
    selected_close_col = _first_existing(work, (close_col, "Close", "EndPrice"))
    if selected_return_col is not None:
        work["TickerReturn"] = _numeric(work[selected_return_col])
    if selected_price_col is not None:
        work["OpenPrice"] = _numeric(work[selected_price_col])
    if selected_close_col is not None:
        close = _numeric(work[selected_close_col])
    if selected_return_col is None:
        if selected_price_col is None or selected_close_col is None:
            raise ValueError("Price input must include Date/Ticker/Open/Close or a Return/TickerReturn/CloseRet/DailyReturn column.")
        with np.errstate(divide="ignore", invalid="ignore"):
            work["TickerReturn"] = np.where(work["OpenPrice"].abs() > EPS, close / work["OpenPrice"] - 1.0, np.nan)
    elif selected_price_col is None and selected_close_col is not None:
        with np.errstate(divide="ignore", invalid="ignore"):
            work["OpenPrice"] = np.where((1.0 + work["TickerReturn"]).abs() > EPS, close / (1.0 + work["TickerReturn"]), np.nan)
    if selected_close_col is not None:
        work["Close"] = close
    elif "OpenPrice" in work.columns:
        work["Close"] = work["OpenPrice"] * (1.0 + work["TickerReturn"])
    if "OpenPrice" in work.columns and "Close" in work.columns:
        with np.errstate(divide="ignore", invalid="ignore"):
            work["TickerReturn"] = np.where(work["OpenPrice"].abs() > EPS, work["Close"] / work["OpenPrice"] - 1.0, np.nan)
    if "ContractMultiplier" in work.columns:
        work["ContractMultiplier"] = _numeric(work["ContractMultiplier"])
    selected_prev_close_col = _first_existing(work, ("PrevClose", "PreviousClose", "PriorClose", "PrevClosePrice"))
    if selected_prev_close_col is not None:
        work["PrevClosePrice"] = _numeric(work[selected_prev_close_col])
    work = work.dropna(subset=["Date"])
    work = work[work["Ticker"].ne("")]
    agg_cols = {"TickerReturn": "mean"}
    for column in ("OpenPrice", "Close", "PrevClosePrice", "ContractMultiplier"):
        if column in work.columns:
            agg_cols[column] = "mean"
    out = work.groupby(["Date", "Ticker"], as_index=False, sort=True).agg(agg_cols).reset_index(drop=True)
    if "Close" in out.columns:
        out = out.sort_values(["Ticker", "Date"], kind="mergesort").reset_index(drop=True)
        shifted_close = out.groupby("Ticker", sort=False)["Close"].shift(1)
        if "PrevClosePrice" in out.columns:
            out["PrevClosePrice"] = _numeric(out["PrevClosePrice"]).fillna(shifted_close)
        else:
            out["PrevClosePrice"] = shifted_close
        if "OpenPrice" in out.columns:
            out["PrevClosePrice"] = out["PrevClosePrice"].fillna(out["OpenPrice"])
        out = out.sort_values(["Date", "Ticker"], kind="mergesort").reset_index(drop=True)
    return out


def positions_from_trade_frame(
    trades: pd.DataFrame,
    returns: pd.DataFrame,
    spec: PositionInputSpec | None = None,
) -> pd.DataFrame:
    """把目标交易或 delta 交易行展开为每日向前持有的持仓。

    日期代表生效日期。如果研究需要 T+1 执行，应在调用本函数前先移动交易目标日期。
    """

    cfg = spec or PositionInputSpec(mode="target_trades")
    mode = _coerce_mode(cfg.mode)
    normalized_returns = normalize_return_frame(
        returns,
        price_col=cfg.price_col,
        close_col=cfg.close_col,
    )
    if mode == "positions":
        return normalize_position_frame(trades, cfg, returns=normalized_returns)
    trade_targets = normalize_position_frame(trades, cfg, returns=normalized_returns)
    return_dates = pd.to_datetime(normalized_returns["Date"], errors="coerce").dropna().dt.normalize().drop_duplicates().sort_values()
    if return_dates.empty:
        raise ValueError("Return input has no valid dates.")

    by_date = {date: frame for date, frame in trade_targets.groupby("Date", sort=True)}
    current: dict[str, float] = {}
    rows: list[dict[str, Any]] = []
    for date in return_dates.tolist():
        date = pd.Timestamp(date).normalize()
        if date in by_date:
            frame = by_date[date]
            if mode == "target_trades":
                value_col = "TargetQuantity" if "TargetQuantity" in frame.columns else "Weight"
                updates = {str(row["Ticker"]): float(row[value_col]) for _, row in frame.iterrows()}
                if bool(cfg.replace_book_on_trade_date):
                    current = updates
                else:
                    current.update(updates)
            else:
                value_col = "TargetQuantity" if "TargetQuantity" in frame.columns else "Weight"
                for _, row in frame.iterrows():
                    ticker = str(row["Ticker"])
                    current[ticker] = float(current.get(ticker, 0.0) + float(row[value_col]))
            current = {ticker: weight for ticker, weight in current.items() if abs(float(weight)) > EPS}
        for ticker, weight in sorted(current.items()):
            if "TargetQuantity" in trade_targets.columns:
                rows.append({"Date": date, "Ticker": ticker, "TargetQuantity": float(weight)})
            else:
                rows.append({"Date": date, "Ticker": ticker, "Weight": float(weight)})
    carried = pd.DataFrame(rows)
    if carried.empty:
        columns = ["Date", "Ticker", "TargetQuantity"] if "TargetQuantity" in trade_targets.columns else ["Date", "Ticker", "Weight"]
        return pd.DataFrame(columns=columns)
    if "TargetQuantity" in carried.columns:
        return normalize_position_frame(carried, cfg, returns=returns)
    return carried[["Date", "Ticker", "Weight"]]


def _build_daily_from_quantities(
    *,
    positions: pd.DataFrame,
    returns: pd.DataFrame,
    input_spec: PositionInputSpec,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    policy = str(input_spec.missing_return_policy or "zero").strip().lower()
    if policy not in {"zero", "drop", "raise"}:
        raise ValueError(f"Unsupported missing_return_policy: {input_spec.missing_return_policy}")
    if "OpenPrice" not in returns.columns:
        raise ValueError("Quantity accounting requires Open/StartPrice in the ticker returns frame.")
    if "Close" not in returns.columns:
        raise ValueError("Quantity accounting requires Close or Open/StartPrice + Return in the ticker price frame.")

    cap = float(input_spec.capital_base)
    if cap <= EPS:
        raise ValueError("Quantity accounting requires positive capital_base.")
    slippage_rate = float(input_spec.open_slippage_bps) / 10_000.0
    returns_map = {
        (pd.Timestamp(row["Date"]).normalize(), str(row["Ticker"])): row
        for _, row in returns.iterrows()
    }
    all_dates = pd.to_datetime(returns["Date"], errors="coerce").dropna().dt.normalize().drop_duplicates().sort_values().tolist()
    by_date = {date: frame for date, frame in positions.groupby("Date", sort=True)}
    previous_quantities: dict[str, float] = {}
    rows: list[dict[str, Any]] = []
    holding_rows: list[dict[str, Any]] = []

    for raw_date in all_dates:
        date = pd.Timestamp(raw_date).normalize()
        frame = by_date.get(date, pd.DataFrame(columns=positions.columns))
        current_quantities = {
            str(row["Ticker"]): float(row["TargetQuantity"])
            for _, row in frame.iterrows()
            if abs(float(row["TargetQuantity"])) > EPS
        }
        tickers = sorted(set(previous_quantities) | set(current_quantities))
        total_pnl = 0.0
        long_pnl = 0.0
        short_pnl = 0.0
        existing_position_pnl_total = 0.0
        overnight_gap_pnl_total = 0.0
        intraday_pnl_total = 0.0
        slippage_cost_total = 0.0
        trade_notional = 0.0
        gross_notional = 0.0
        long_notional = 0.0
        short_notional = 0.0
        covered = 0

        for ticker in tickers:
            prev_qty = float(previous_quantities.get(ticker, 0.0))
            target_qty = float(current_quantities.get(ticker, 0.0))
            delta_qty = target_qty - prev_qty
            ret_row = returns_map.get((date, ticker))
            if ret_row is None:
                if policy == "raise":
                    raise ValueError(f"Missing return/price row for {ticker} on {date.date()}.")
                if policy == "drop":
                    continue
                open_price = close_price = prev_close = 0.0
                multiplier = float(input_spec.default_contract_multiplier)
                has_return = False
            else:
                open_price = float(pd.to_numeric(pd.Series([ret_row.get("OpenPrice")]), errors="coerce").fillna(0.0).iloc[0])
                close_price = float(pd.to_numeric(pd.Series([ret_row.get("Close")]), errors="coerce").fillna(open_price).iloc[0])
                prev_close = float(pd.to_numeric(pd.Series([ret_row.get("PrevClosePrice")]), errors="coerce").fillna(open_price).iloc[0])
                multiplier = float(
                    pd.to_numeric(pd.Series([ret_row.get("ContractMultiplier")]), errors="coerce")
                    .fillna(float(input_spec.default_contract_multiplier))
                    .iloc[0]
                )
                has_return = bool(open_price > EPS)
            overnight_gap_pnl = prev_qty * (open_price - prev_close) * multiplier
            existing_position_pnl = prev_qty * (close_price - prev_close) * multiplier
            intraday_pnl = delta_qty * (close_price - open_price) * multiplier
            slippage_cost = abs(delta_qty) * open_price * multiplier * slippage_rate
            pnl = existing_position_pnl + intraday_pnl - slippage_cost
            current_notional = target_qty * open_price * multiplier
            name_trade_notional = abs(delta_qty) * open_price * multiplier

            total_pnl += pnl
            existing_position_pnl_total += existing_position_pnl
            overnight_gap_pnl_total += overnight_gap_pnl
            intraday_pnl_total += intraday_pnl
            slippage_cost_total += slippage_cost
            trade_notional += name_trade_notional
            gross_notional += abs(current_notional)
            if current_notional > 0.0:
                long_notional += current_notional
                long_pnl += intraday_pnl - slippage_cost
            elif current_notional < 0.0:
                short_notional += abs(current_notional)
                short_pnl += intraday_pnl - slippage_cost
            if has_return:
                covered += 1
            holding_rows.append(
                {
                    "Date": date,
                    "Ticker": ticker,
                    "PreviousQuantity": prev_qty,
                    "TargetQuantity": target_qty,
                    "DeltaQuantity": delta_qty,
                    "OpenPrice": open_price,
                    "Close": close_price,
                    "PrevClosePrice": prev_close,
                    "ContractMultiplier": multiplier,
                    "OpenNotional": current_notional,
                    "TradeNotional": name_trade_notional,
                    "ExistingPositionPnL": existing_position_pnl,
                    "OvernightGapPnL": overnight_gap_pnl,
                    "IntradayPnL": intraday_pnl,
                    "RebalancePnL": intraday_pnl,
                    "OpenSlippageCost": slippage_cost,
                    "PnL": pnl,
                    "Weight": current_notional / cap,
                    "HasReturn": has_return,
                }
            )

        names = int(sum(abs(qty) > EPS for qty in current_quantities.values()))
        gross = gross_notional / cap
        long_gross = long_notional / cap
        short_gross = short_notional / cap
        net = sum(
            qty
            * float(pd.to_numeric(pd.Series([returns_map.get((date, ticker), {}).get("OpenPrice") if returns_map.get((date, ticker)) is not None else 0.0]), errors="coerce").fillna(0.0).iloc[0])
            * float(pd.to_numeric(pd.Series([returns_map.get((date, ticker), {}).get("ContractMultiplier") if returns_map.get((date, ticker)) is not None else input_spec.default_contract_multiplier]), errors="coerce").fillna(input_spec.default_contract_multiplier).iloc[0])
            for ticker, qty in current_quantities.items()
        ) / cap
        long_leg_return = (long_pnl / cap) / long_gross if long_gross > EPS else np.nan
        short_leg_return = (short_pnl / cap) / short_gross if short_gross > EPS else np.nan
        central_return = _safe_pnl_return(total_pnl, gross_notional)
        if long_gross > EPS and short_gross > EPS:
            selection_return = 0.5 * long_leg_return + 0.5 * short_leg_return
        else:
            selection_return = central_return
        rows.append(
            {
                "Date": date,
                "CentralBookPnL": total_pnl,
                "CentralBookCapitalReturn": total_pnl / cap,
                "CentralBookReturn": central_return,
                "ExistingPositionPnL": existing_position_pnl_total,
                "ExistingPositionReturn": _safe_pnl_return(existing_position_pnl_total, gross_notional),
                "OvernightGapPnL": overnight_gap_pnl_total,
                "OvernightGapReturn": _safe_pnl_return(overnight_gap_pnl_total, gross_notional),
                "IntradayPnL": intraday_pnl_total,
                "IntradayReturn": _safe_pnl_return(intraday_pnl_total, gross_notional),
                "RebalancePnL": intraday_pnl_total,
                "RebalanceReturn": _safe_pnl_return(intraday_pnl_total, gross_notional),
                "OpenSlippageCost": slippage_cost_total,
                "OpenSlippageReturn": _safe_pnl_return(-slippage_cost_total, gross_notional),
                "CentralBookGrossStart": gross,
                "LongGrossStart": long_gross,
                "ShortGrossStart": short_gross,
                "NetGrossStart": net,
                "NetRatioStart": float(net / gross) if gross > EPS else np.nan,
                "LongLegReturn": long_leg_return,
                "ShortLegReturn": short_leg_return,
                "SelectionReturn": selection_return,
                "NetTimingReturn": float(central_return - selection_return),
                "Names": names,
                "CentralBookTradeNotional": trade_notional,
                "CentralBookTradeWeight": trade_notional / cap,
                "CentralBookTurnover": float(0.5 * trade_notional / gross_notional) if gross_notional > EPS else 0.0,
                "DirectNameCoverage": float(covered / len(tickers)) if tickers else np.nan,
                "CoveredNameShare": float(covered / len(tickers)) if tickers else np.nan,
                "MissingReturnCount": int(len(tickers) - covered),
            }
        )
        previous_quantities = current_quantities

    daily = pd.DataFrame(rows)
    holdings = pd.DataFrame(holding_rows)
    if not holdings.empty:
        holdings = holdings.sort_values(["Date", "Ticker"], kind="mergesort").reset_index(drop=True)
    return daily, holdings


def _build_daily_from_positions(
    *,
    positions: pd.DataFrame,
    returns: pd.DataFrame,
    input_spec: PositionInputSpec,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if "TargetQuantity" in positions.columns:
        return _build_daily_from_quantities(
            positions=positions,
            returns=returns,
            input_spec=input_spec,
        )
    policy = str(input_spec.missing_return_policy or "zero").strip().lower()
    if policy not in {"zero", "drop", "raise"}:
        raise ValueError(f"Unsupported missing_return_policy: {input_spec.missing_return_policy}")
    merged = positions.merge(returns, on=["Date", "Ticker"], how="left", indicator=True)
    missing_mask = merged["TickerReturn"].isna()
    if missing_mask.any() and policy == "raise":
        sample = merged.loc[missing_mask, ["Date", "Ticker"]].head(10).to_dict("records")
        raise ValueError(f"Missing ticker returns for {int(missing_mask.sum())} position rows. Sample: {sample}")
    if policy == "drop":
        merged = merged.loc[~missing_mask].copy()
    else:
        merged["TickerReturn"] = merged["TickerReturn"].fillna(0.0)
    merged["TickerPnLReturn"] = merged["Weight"] * merged["TickerReturn"]
    merged["LongWeight"] = merged["Weight"].clip(lower=0.0)
    merged["ShortWeightAbs"] = (-merged["Weight"].clip(upper=0.0)).astype(float)
    merged["LongPnLReturn"] = merged["TickerPnLReturn"].where(merged["Weight"].gt(0.0), 0.0)
    merged["ShortPnLReturn"] = merged["TickerPnLReturn"].where(merged["Weight"].lt(0.0), 0.0)
    merged["HasReturn"] = ~missing_mask

    rows: list[dict[str, Any]] = []
    previous_weights: dict[str, float] | None = None
    all_dates = returns["Date"].drop_duplicates().sort_values().tolist()
    by_date = {date: frame for date, frame in merged.groupby("Date", sort=True)}
    for date in all_dates:
        date = pd.Timestamp(date).normalize()
        frame = by_date.get(date, pd.DataFrame(columns=merged.columns))
        current_weights = {
            str(row["Ticker"]): float(row["Weight"])
            for _, row in frame.iterrows()
            if abs(float(row["Weight"])) > EPS
        }
        gross = float(sum(abs(weight) for weight in current_weights.values()))
        long_gross = float(sum(max(weight, 0.0) for weight in current_weights.values()))
        short_gross = float(sum(abs(min(weight, 0.0)) for weight in current_weights.values()))
        net = float(sum(current_weights.values()))
        strategy_return = float(pd.to_numeric(frame.get("TickerPnLReturn"), errors="coerce").fillna(0.0).sum()) if not frame.empty else 0.0
        long_pnl = float(pd.to_numeric(frame.get("LongPnLReturn"), errors="coerce").fillna(0.0).sum()) if not frame.empty else 0.0
        short_pnl = float(pd.to_numeric(frame.get("ShortPnLReturn"), errors="coerce").fillna(0.0).sum()) if not frame.empty else 0.0
        if previous_weights is None:
            trade_weight = np.nan
            turnover = np.nan
        else:
            tickers = set(previous_weights) | set(current_weights)
            trade_weight = float(sum(abs(current_weights.get(ticker, 0.0) - previous_weights.get(ticker, 0.0)) for ticker in tickers))
            turnover = float(0.5 * trade_weight / gross) if gross > EPS else 0.0
        covered = int(frame["HasReturn"].sum()) if "HasReturn" in frame.columns else 0
        names = int(len(current_weights))
        long_leg_return = float(long_pnl / long_gross) if long_gross > EPS else np.nan
        short_leg_return = float(short_pnl / short_gross) if short_gross > EPS else np.nan
        central_return = _safe_pnl_return(strategy_return, gross)
        if long_gross > EPS and short_gross > EPS:
            selection_return = 0.5 * long_leg_return + 0.5 * short_leg_return
        else:
            selection_return = central_return
        rows.append(
            {
                "Date": date,
                "CentralBookCapitalReturn": strategy_return,
                "CentralBookReturn": central_return,
                "CentralBookGrossStart": gross,
                "LongGrossStart": long_gross,
                "ShortGrossStart": short_gross,
                "NetGrossStart": net,
                "NetRatioStart": float(net / gross) if gross > EPS else np.nan,
                "LongLegReturn": long_leg_return,
                "ShortLegReturn": short_leg_return,
                "SelectionReturn": selection_return,
                "NetTimingReturn": float(central_return - selection_return),
                "Names": names,
                "CentralBookTradeWeight": trade_weight,
                "CentralBookTurnover": turnover,
                "DirectNameCoverage": float(covered / names) if names else np.nan,
                "CoveredNameShare": float(covered / names) if names else np.nan,
                "MissingReturnCount": int(names - covered),
            }
        )
        previous_weights = current_weights
    daily = pd.DataFrame(rows)
    holdings = merged[["Date", "Ticker", "Weight", "TickerReturn", "TickerPnLReturn", "HasReturn"]].copy()
    holdings = holdings.sort_values(["Date", "Ticker"], kind="mergesort").reset_index(drop=True)
    return daily, holdings


def run_backtest_from_position_input(
    *,
    positions: pd.DataFrame,
    returns: pd.DataFrame,
    spec: BacktestSpec | None = None,
    input_spec: PositionInputSpec | None = None,
    benchmark_returns: pd.DataFrame | None = None,
    output_dir: Path | str | None = None,
) -> StandardRunOutput:
    """基于持仓或交易目标输入运行标准回测。"""

    backtest_spec = spec or BacktestSpec(name="position_input_backtest")
    cfg = input_spec or PositionInputSpec()
    normalized_returns = normalize_return_frame(
        returns,
        price_col=cfg.price_col,
        close_col=cfg.close_col,
    )
    mode = _coerce_mode(cfg.mode)
    if mode == "positions":
        normalized_positions = normalize_position_frame(positions, cfg, returns=normalized_returns)
    else:
        normalized_positions = positions_from_trade_frame(positions, normalized_returns, cfg)
    daily, holdings = _build_daily_from_positions(
        positions=normalized_positions,
        returns=normalized_returns,
        input_spec=cfg,
    )
    if benchmark_returns is not None and not benchmark_returns.empty:
        benchmark = benchmark_returns.copy()
        if "Date" not in benchmark.columns:
            raise ValueError("benchmark_returns must include Date.")
        benchmark["Date"] = pd.to_datetime(benchmark["Date"], errors="coerce").dt.normalize()
        benchmark = benchmark.dropna(subset=["Date"]).drop_duplicates("Date", keep="last")
        daily = daily.merge(benchmark, on="Date", how="left")
    result = BacktestResult(
        spec=backtest_spec,
        daily=daily,
        holdings=holdings,
        trades=normalized_positions if mode != "positions" else pd.DataFrame(),
        tables={
            "input_positions": normalized_positions,
            "input_returns": normalized_returns,
        },
        raw_metadata={
            "input_mode": mode,
            "missing_return_policy": cfg.missing_return_policy,
        },
    )
    metrics = compute_standard_metrics(result)
    artifacts: dict[str, str] = {}
    if output_dir is not None:
        artifacts = write_standard_report(result, output_dir, metrics=metrics)
    return StandardRunOutput(result=result, metrics=metrics, artifacts=artifacts)

