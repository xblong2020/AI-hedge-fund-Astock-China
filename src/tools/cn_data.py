"""
China A-Share data provider.
Primary: AKShare | Fallback: Tushare
"""

import logging
import os
import re
from typing import Optional

from src.data.models import (
    Price,
    FinancialMetrics,
    CompanyNews,
    InsiderTrade,
    CompanyFacts,
    LineItem,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ticker detection & normalization
# ---------------------------------------------------------------------------

CN_TICKER_RE = re.compile(r"^\d{6}(\.(SZ|SS|SH|BJ))?$", re.IGNORECASE)


def _is_cn_ticker(ticker: str) -> bool:
    return bool(CN_TICKER_RE.match(ticker.strip()))


def _normalize_cn_ticker(ticker: str) -> tuple[str, str]:
    t = ticker.strip().upper()
    if "." in t:
        code, market = t.split(".", 1)
        return code, t
    if t.startswith(("0", "3", "2")):
        return t, f"{t}.SZ"
    elif t.startswith(("6", "9")):
        return t, f"{t}.SH"
    elif t.startswith(("4", "8")):
        return t, f"{t}.BJ"
    return t, t


# ---------------------------------------------------------------------------
# Tushare client (lazy singleton)
# ---------------------------------------------------------------------------

_tushare_pro = None


def _get_tushare():
    global _tushare_pro
    if _tushare_pro is not None:
        return _tushare_pro
    token = os.environ.get("TUSHARE_TOKEN", "")
    if not token:
        logger.warning("TUSHARE_TOKEN not set in .env")
        return None
    try:
        import tushare as ts
        _tushare_pro = ts.pro_api(token)
        tushare_url = os.environ.get("TUSHARE_URL", "")
        if tushare_url:
            _tushare_pro._DataApi__http_url = tushare_url
        return _tushare_pro
    except Exception as e:
        logger.warning("Failed to init Tushare: %s", e)
        return None


# ---------------------------------------------------------------------------
# Column name mapping (AKShare returns Chinese column names)
# ---------------------------------------------------------------------------

# AKShare stock_zh_a_hist column names
AK_OPEN = "\u5f00\u76d8"
AK_CLOSE = "\u6536\u76d8"
AK_HIGH = "\u6700\u9ad8"
AK_LOW = "\u6700\u4f4e"
AK_VOLUME = "\u6210\u4ea4\u91cf"
AK_DATE = "\u65e5\u671f"






# ---------------------------------------------------------------------------
# Tushare API response cache (avoids rate-limiting from concurrent agent calls)
# ---------------------------------------------------------------------------

import hashlib as _hashlib
import time as _time_module
import math

_tushare_cache = {}       # key -> (timestamp, dataframe)
_CACHE_TTL = 300          # 5 minutes

# ---------------------------------------------------------------------------
# Session-level pre-fetch cache (lives for the entire program run)
# ---------------------------------------------------------------------------

_session_store = {}  # key: (ticker, end_date) -> dict of pre-fetched data

def prefetch_cn_data(ticker: str, end_date: str, start_date: str = None):
    """Pre-fetch ALL Tushare data for a ticker in one batch.
    Subsequent calls to get_cn_* functions will read from cache.
    """
    import pandas as pd
    
    _, ts_code = _normalize_cn_ticker(ticker)
    clean_end = end_date.replace("-", "")
    clean_start = (start_date or "20200101").replace("-", "")
    
    store_key = (ticker, end_date)
    if store_key in _session_store:
        return _session_store[store_key]
    
    pro = _get_tushare()
    if pro is None:
        logger.warning("prefetch: Tushare not available")
        return {}
    
    store = {
        "prices": None,
        "financial_metrics": None,
        "line_items": {},
        "pe_pb_mktcap": None,
        "ts_code": ts_code,
    }
    
    try:
        # 1) Prices
        logger.info("prefetch: fetching prices for %s", ticker)
        df_price = pro.daily(ts_code=ts_code, start_date=clean_start, end_date=clean_end)
        if df_price is not None and not df_price.empty:
            store["prices"] = df_price.copy()
    except Exception as e:
        logger.warning("prefetch prices failed: %s", e)
    
    try:
        # 2) Financial indicators (fina_indicator)
        logger.info("prefetch: fetching fina_indicator for %s", ticker)
        df_fina = pro.fina_indicator(ts_code=ts_code, end_date=clean_end, limit=10)
        if df_fina is not None and not df_fina.empty:
            store["financial_metrics"] = df_fina.copy()
    except Exception as e:
        logger.warning("prefetch fina_indicator failed: %s", e)
    
    try:
        # 3) Income statement
        logger.info("prefetch: fetching income statement for %s", ticker)
        df_income = pro.income(ts_code=ts_code, end_date=clean_end, limit=10)
        if df_income is not None and not df_income.empty:
            store["line_items"]["income"] = df_income.copy()
    except Exception as e:
        logger.warning("prefetch income failed: %s", e)
    
    try:
        # 4) Balance sheet
        logger.info("prefetch: fetching balance sheet for %s", ticker)
        df_bs = pro.balancesheet(ts_code=ts_code, end_date=clean_end, limit=10)
        if df_bs is not None and not df_bs.empty:
            store["line_items"]["balancesheet"] = df_bs.copy()
    except Exception as e:
        logger.warning("prefetch balancesheet failed: %s", e)
    
    try:
        # 5) Cash flow
        logger.info("prefetch: fetching cash flow for %s", ticker)
        df_cf = pro.cashflow(ts_code=ts_code, end_date=clean_end, limit=10)
        if df_cf is not None and not df_cf.empty:
            store["line_items"]["cashflow"] = df_cf.copy()
    except Exception as e:
        logger.warning("prefetch cashflow failed: %s", e)
    
    try:
        # 6) PE/PB/market_cap via daily_basic (with 10-day fallback)
        logger.info("prefetch: fetching PE/PB/market_cap for %s", ticker)
        store["pe_pb_mktcap"] = _get_pe_pb_mktcap(ticker, end_date)
    except Exception as e:
        logger.warning("prefetch PE/PB/mktcap failed: %s", e)
    
    _session_store[store_key] = store
    logger.info("prefetch: completed for %s (%s)", ticker, ts_code)
    return store


def _get_session_store(ticker: str, end_date: str) -> dict:
    """Get pre-fetched data for a ticker."""
    return _session_store.get((ticker, end_date), {})


def _cached_tushare_call(func_name: str, **kwargs):
    """Cache wrapper for Tushare API calls. Prevents duplicate calls from concurrent agents."""
    pro = _get_tushare()
    if pro is None:
        return None
    key = _hashlib.md5(f"{func_name}:{sorted(kwargs.items())}".encode()).hexdigest()
    now = _time_module.time()
    if key in _tushare_cache:
        ts_val, df = _tushare_cache[key]
        if now - ts_val < _CACHE_TTL:
            return df.copy() if df is not None else None
    try:
        func = getattr(pro, func_name)
        result = func(**kwargs)
        _tushare_cache[key] = (now, result.copy() if result is not None else None)
        return result
    except Exception:
        return None

# ---------------------------------------------------------------------------
# Tencent quote (PE/PB/market_cap fallback)
# ---------------------------------------------------------------------------

import time as _time
import requests as _requests
from datetime import datetime as _dt, timedelta as _td

_TENCENT_CACHE = {}
_TENCENT_CACHE_TS = {}


def _get_tencent_quote(ticker: str) -> dict:
    """Fetch PE/PB/market_cap from Tencent qt.gtimg.cn (cached 60s)."""
    now = _time.time()
    if ticker in _TENCENT_CACHE and (now - _TENCENT_CACHE_TS.get(ticker, 0)) < 60:
        return _TENCENT_CACHE[ticker]
    pure_code, _ = _normalize_cn_ticker(ticker)
    market = "sh" if ticker.startswith("6") or ticker.upper().endswith(".SH") else "sz"
    url = f"http://qt.gtimg.cn/q={market}{pure_code}"
    try:
        resp = _requests.get(url, timeout=5)
        parts = resp.text.split("~")
        if len(parts) < 47:
            return {}
        result = {
            "pe": float(parts[39]) if parts[39] and parts[39].replace(".","").replace("-","").isdigit() else None,
            "pb": float(parts[46]) if parts[46] and parts[46].replace(".","").replace("-","").isdigit() else None,
            "market_cap": float(parts[44]) * 1e8 if parts[44] and parts[44].replace(".","").isdigit() else None,
        }
        _TENCENT_CACHE[ticker] = result
        _TENCENT_CACHE_TS[ticker] = now
        return result
    except Exception:
        return {}


def _get_pe_pb_mktcap(ticker: str, end_date: str) -> dict:
    """Get PE, PB, market_cap. Tushare daily_basic (with 10-day fallback) > Tencent."""
    pro = _get_tushare()
    _, ts_code = _normalize_cn_ticker(ticker)
    clean_date = end_date.replace("-", "")
    if pro:
        for days_back in range(10):
            try:
                dt = (_dt.strptime(clean_date, "%Y%m%d") - _td(days=days_back)).strftime("%Y%m%d")
                df = _cached_tushare_call("daily_basic", ts_code=ts_code, trade_date=dt, fields="trade_date,total_mv,pe,pb")
                if df is not None and not df.empty:
                    r = df.iloc[0]
                    mv = r.get("total_mv")
                    pe = r.get("pe")
                    pb = r.get("pb")
                    return {
                        "pe": float(pe) if pe is not None and float(pe) > 0 else None,
                        "pb": float(pb) if pb is not None and float(pb) > 0 else None,
                        "market_cap": float(mv) * 1e4 if mv is not None and float(mv) > 0 else None,
                    }
            except Exception:
                continue
    return _get_tencent_quote(ticker)

# ---------------------------------------------------------------------------
# Prices (AKShare primary, Tushare fallback)
# ---------------------------------------------------------------------------

def get_cn_prices(
    ticker: str,
    start_date: str,
    end_date: str,
) -> list[Price]:
    # Check session cache first
    store = _get_session_store(ticker, end_date)
    if store and store.get("prices") is not None:
        df = store["prices"]
        prices = []
        for _, row in df.iterrows():
            prices.append(Price(
                open=float(row["open"]),
                close=float(row["close"]),
                high=float(row["high"]),
                low=float(row["low"]),
                volume=int(row["vol"]),
                time=str(row["trade_date"])[:10],
            ))
        if prices:
            return prices

    pure_code, _ = _normalize_cn_ticker(ticker)

    # 1) Try AKShare
    try:
        import akshare as ak
        df = ak.stock_zh_a_hist(
            symbol=pure_code,
            period="daily",
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
            adjust="qfq",
        )
        if df is not None and not df.empty:
            prices = []
            for _, row in df.iterrows():
                prices.append(Price(
                    open=float(row[AK_OPEN]),
                    close=float(row[AK_CLOSE]),
                    high=float(row[AK_HIGH]),
                    low=float(row[AK_LOW]),
                    volume=int(row[AK_VOLUME]),
                    time=str(row[AK_DATE])[:10],
                ))
            if prices:
                return prices
    except Exception as e:
        logger.warning("AKShare get_prices failed for %s: %s", ticker, e)

    # 2) Fallback: Tushare
    pro = _get_tushare()
    if pro is None:
        return []

    try:
        _, ts_code = _normalize_cn_ticker(ticker)
        df = pro.daily(ts_code=ts_code, start_date=start_date.replace("-", ""), end_date=end_date.replace("-", ""))
        if df is not None and not df.empty:
            df = df.sort_values("trade_date")
            prices = []
            for _, row in df.iterrows():
                prices.append(Price(
                    open=float(row["open"]),
                    close=float(row["close"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    volume=int(row["vol"]),
                    time=str(row["trade_date"]),
                ))
            return prices
    except Exception as e:
        logger.warning("Tushare get_prices failed for %s: %s", ticker, e)

    return []


# ---------------------------------------------------------------------------
# Financial Metrics (Tushare primary)
# ---------------------------------------------------------------------------

def get_cn_financial_metrics(
    ticker: str,
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
) -> list[FinancialMetrics]:
    # Check session cache first
    store = _get_session_store(ticker, end_date)
    _, ts_code = _normalize_cn_ticker(ticker)
    
    if store and store.get("financial_metrics") is not None:
        df = store["financial_metrics"]
        results = []
        for _, row in df.head(limit).iterrows():
            results.append(FinancialMetrics(
                ticker=ticker,
                report_period=str(row.get("end_date", ""))[:10],
                period=period,
                currency="CNY",
                return_on_equity=float(row["roe"]) / 100 if row.get("roe") and float(row.get("roe", 0)) != 0 else None,
                return_on_assets=float(row["roa"]) / 100 if row.get("roa") and float(row.get("roa", 0)) != 0 else None,
                return_on_invested_capital=float(row["roic"]) / 100 if row.get("roic") and float(row.get("roic", 0)) != 0 else None,
                gross_margin=float(row["grossprofit_margin"]) / 100 if row.get("grossprofit_margin") and float(row.get("grossprofit_margin", 0)) != 0 else None,
                net_margin=float(row["netprofit_margin"]) / 100 if row.get("netprofit_margin") and float(row.get("netprofit_margin", 0)) != 0 else None,
                operating_margin=float(row["op_of_gr"]) / 100 if row.get("op_of_gr") and float(row.get("op_of_gr", 0)) != 0 else None,
                debt_to_assets=float(row["debt_to_assets"]) / 100 if row.get("debt_to_assets") and float(row.get("debt_to_assets", 0)) != 0 else None,
                debt_to_equity=float(row["debt_to_eqt"]) if row.get("debt_to_eqt") and float(row.get("debt_to_eqt", 0)) > 0 else None,
                interest_coverage=float(row["ebit"]) / abs(float(row.get("finaexp_of_gr", 1))) if row.get("ebit") and row.get("finaexp_of_gr") and float(row.get("finaexp_of_gr", 0)) != 0 else None,
                market_cap=None,
                price_to_earnings_ratio=None,
                price_to_book_ratio=None,
                current_ratio=float(row["current_ratio"]) if row.get("current_ratio") and float(row.get("current_ratio", 0)) > 0 else None,
                quick_ratio=float(row["quick_ratio"]) if row.get("quick_ratio") and float(row.get("quick_ratio", 0)) > 0 else None,
                earnings_per_share=float(row["eps"]) if row.get("eps") and float(row.get("eps", 0)) > 0 else None,
                book_value_per_share=float(row["bps"]) if row.get("bps") and float(row.get("bps", 0)) > 0 else None,
                free_cash_flow_per_share=float(row["fcff_ps"]) if row.get("fcff_ps") and float(row.get("fcff_ps", 0)) > 0 else None,
                revenue_growth=float(row["or_yoy"]) / 100 if row.get("or_yoy") and float(row.get("or_yoy", 0)) != 0 else None,
                earnings_growth=float(row["netprofit_yoy"]) / 100 if row.get("netprofit_yoy") and float(row.get("netprofit_yoy", 0)) != 0 else None,
                operating_income_growth=float(row["op_yoy"]) / 100 if row.get("op_yoy") and float(row.get("op_yoy", 0)) != 0 else None,
                book_value_growth=float(row["bps_yoy"]) / 100 if row.get("bps_yoy") and float(row.get("bps_yoy", 0)) != 0 else None,
                earnings_per_share_growth=float(row["basic_eps_yoy"]) / 100 if row.get("basic_eps_yoy") and float(row.get("basic_eps_yoy", 0)) != 0 else None,
            ))
        # Inject PE/PB/market_cap
        ext = store.get("pe_pb_mktcap") or _get_pe_pb_mktcap(ticker, end_date)
        for r in results:
            r.market_cap = ext.get("market_cap")
            r.price_to_earnings_ratio = ext.get("pe")
            r.price_to_book_ratio = ext.get("pb")
            # Find matching row for computed fields (single pass)
            for _, row in df.head(limit).iterrows():
                if str(row.get("end_date", ""))[:10] == r.report_period:
                    fcff_val = row.get("fcff")
                    if fcff_val is not None and r.market_cap and r.market_cap > 0:
                        r.free_cash_flow_yield = float(fcff_val) / r.market_cap
                    # Compute EV from netdebt + market_cap (independent of ebitda)
                    nd = row.get("netdebt")
                    if nd is not None and r.market_cap and not (isinstance(nd, float) and math.isnan(nd)):
                        netdebt_val = float(nd)
                        ev = r.market_cap + netdebt_val
                        r.enterprise_value = ev
                        # EV/EBITDA (only if ebitda available and > 0)
                        ebitda_val = row.get("ebitda")
                        if ebitda_val is not None and not (isinstance(ebitda_val, float) and math.isnan(ebitda_val)) and float(ebitda_val) > 0:
                            r.enterprise_value_to_ebitda_ratio = ev / float(ebitda_val)
                            logger.debug("EV/EBITDA computed for %s: ev=%.0f ebitda=%.0f ratio=%.1f", r.ticker, ev, float(ebitda_val), r.enterprise_value_to_ebitda_ratio)
                        # EV/EBIT (only if ebit available and != 0)
                        ebit_val = row.get("ebit")
                        if ebit_val is not None and not (isinstance(ebit_val, float) and math.isnan(ebit_val)) and float(ebit_val) != 0:
                            r.ev_to_ebit = ev / float(ebit_val)
                            logger.debug("EV/EBIT computed for %s: ev=%.0f ebit=%.0f ratio=%.1f", r.ticker, ev, float(ebit_val), r.ev_to_ebit)
                        else:
                            logger.debug("EV/EBIT skipped for %s: ebit=%s", r.ticker, ebit_val)
                    else:
                        logger.debug("EV block skipped for %s: netdebt=%s mktcap=%s", r.ticker, nd, r.market_cap)
                    if r.market_cap:
                        income_df = store.get("line_items", {}).get("income") if store else None
                        if income_df is not None:
                            for _, inc_row in income_df.iterrows():
                                inc_end = str(inc_row.get("end_date", inc_row.get("f_ann_date", "")))
                                if inc_end[:10] == r.report_period:
                                    rev = inc_row.get("total_revenue") or inc_row.get("revenue")
                                    if rev is not None:
                                        try:
                                            rv = float(rev)
                                            if rv > 0:
                                                r.price_to_sales_ratio = r.market_cap / rv
                                        except (ValueError, TypeError):
                                            pass
                                    break
                    if r.price_to_earnings_ratio and r.earnings_growth and r.earnings_growth > 0:
                        r.peg_ratio = r.price_to_earnings_ratio / (r.earnings_growth * 100)
                    cur_fcff = row.get("fcff")
                    if cur_fcff is not None and not (isinstance(cur_fcff, float) and math.isnan(cur_fcff)):
                        rp = str(row.get("end_date", ""))[:10]
                        if len(rp) >= 8:
                            try:
                                prev_yr = f"{int(rp[:4])-1}{rp[4:]}"
                                for _, pr in df.iterrows():
                                    if str(pr.get("end_date", ""))[:10] == prev_yr:
                                        pf = pr.get("fcff")
                                        if pf is not None and not (isinstance(pf, float) and math.isnan(pf)) and float(pf) != 0:
                                            r.free_cash_flow_growth = (float(cur_fcff) - float(pf)) / abs(float(pf))
                                        break
                            except Exception:
                                pass
                    break
        return results

    results = []

    pro = _get_tushare()
    if pro is not None:
        try:
            df = pro.fina_indicator(ts_code=ts_code, end_date=end_date.replace("-", ""), limit=limit)
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    results.append(FinancialMetrics(
                        ticker=ticker,
                        report_period=str(row.get("end_date", ""))[:10],
                        period=period,
                        currency="CNY",
                        
                        
                        
                        return_on_equity=float(row["roe"]) / 100 if row.get("roe") and float(row.get("roe", 0)) != 0 else None,
                        return_on_assets=float(row["roa"]) / 100 if row.get("roa") and float(row.get("roa", 0)) != 0 else None,
                        return_on_invested_capital=float(row["roic"]) / 100 if row.get("roic") and float(row.get("roic", 0)) != 0 else None,
                        gross_margin=float(row["grossprofit_margin"]) / 100 if row.get("grossprofit_margin") and float(row.get("grossprofit_margin", 0)) != 0 else None,
                        net_margin=float(row["netprofit_margin"]) / 100 if row.get("netprofit_margin") and float(row.get("netprofit_margin", 0)) != 0 else None,
                        operating_margin=float(row["op_of_gr"]) / 100 if row.get("op_of_gr") and float(row.get("op_of_gr", 0)) != 0 else None,
                        debt_to_assets=float(row["debt_to_assets"]) / 100 if row.get("debt_to_assets") and float(row.get("debt_to_assets", 0)) != 0 else None,
                        debt_to_equity=float(row["debt_to_eqt"]) if row.get("debt_to_eqt") and float(row.get("debt_to_eqt", 0)) > 0 else None,
                        interest_coverage=float(row["ebit"]) / abs(float(row.get("finaexp_of_gr", 1))) if row.get("ebit") and row.get("finaexp_of_gr") and float(row.get("finaexp_of_gr", 0)) != 0 else None,
                        # From daily_basic or Tencent
                        market_cap=None,  # populated below
                        price_to_earnings_ratio=None,
                        price_to_book_ratio=None,
                        current_ratio=float(row["current_ratio"]) if row.get("current_ratio") and float(row.get("current_ratio", 0)) > 0 else None,
                        quick_ratio=float(row["quick_ratio"]) if row.get("quick_ratio") and float(row.get("quick_ratio", 0)) > 0 else None,
                        earnings_per_share=float(row["eps"]) if row.get("eps") and float(row.get("eps", 0)) > 0 else None,
                        book_value_per_share=float(row["bps"]) if row.get("bps") and float(row.get("bps", 0)) > 0 else None,
                        free_cash_flow_per_share=float(row["fcff_ps"]) if row.get("fcff_ps") and float(row.get("fcff_ps", 0)) > 0 else None,
                        revenue_growth=float(row["or_yoy"]) / 100 if row.get("or_yoy") and float(row.get("or_yoy", 0)) != 0 else None,
                        earnings_growth=float(row["netprofit_yoy"]) / 100 if row.get("netprofit_yoy") and float(row.get("netprofit_yoy", 0)) != 0 else None,
                        operating_income_growth=float(row["op_yoy"]) / 100 if row.get("op_yoy") and float(row.get("op_yoy", 0)) != 0 else None,
                        book_value_growth=float(row["bps_yoy"]) / 100 if row.get("bps_yoy") and float(row.get("bps_yoy", 0)) != 0 else None,
                        earnings_per_share_growth=float(row["basic_eps_yoy"]) / 100 if row.get("basic_eps_yoy") and float(row.get("basic_eps_yoy", 0)) != 0 else None,
                    ))
                # Inject PE/PB/market_cap and compute derived fields per-row
                ext = _get_pe_pb_mktcap(ticker, end_date)
                for r in results:
                    r.market_cap = ext.get("market_cap")
                    r.price_to_earnings_ratio = ext.get("pe")
                    r.price_to_book_ratio = ext.get("pb")
                    for _, frow in df.iterrows():
                        if str(frow.get("end_date", ""))[:10] == r.report_period:
                            fcff_val = frow.get("fcff")
                            if fcff_val is not None and r.market_cap and r.market_cap > 0:
                                r.free_cash_flow_yield = float(fcff_val) / r.market_cap
                            nd = frow.get("netdebt")
                            if nd is not None and r.market_cap and not (isinstance(nd, float) and math.isnan(nd)):
                                netdebt_val = float(nd)
                                ev = r.market_cap + netdebt_val
                                r.enterprise_value = ev
                                ebitda_val = frow.get("ebitda")
                                if ebitda_val is not None and not (isinstance(ebitda_val, float) and math.isnan(ebitda_val)) and float(ebitda_val) > 0:
                                    r.enterprise_value_to_ebitda_ratio = ev / float(ebitda_val)
                                ebit_val = frow.get("ebit")
                                if ebit_val is not None and not (isinstance(ebit_val, float) and math.isnan(ebit_val)) and float(ebit_val) != 0:
                                    r.ev_to_ebit = ev / float(ebit_val)
                            # P/S, PEG, fcf_growth (non-cache path)
                            if r.market_cap:
                                rev = frow.get("total_revenue") or frow.get("revenue")
                                if rev is not None:
                                    try:
                                        rv = float(rev)
                                        if rv > 0:
                                            r.price_to_sales_ratio = r.market_cap / rv
                                    except (ValueError, TypeError):
                                        pass
                            if r.price_to_earnings_ratio and r.earnings_growth and r.earnings_growth > 0:
                                r.peg_ratio = r.price_to_earnings_ratio / (r.earnings_growth * 100)
                            cur_fcff = frow.get("fcff")
                            if cur_fcff is not None and not (isinstance(cur_fcff, float) and math.isnan(cur_fcff)):
                                rp = str(frow.get("end_date", ""))[:10]
                                if len(rp) >= 8:
                                    try:
                                        prev_yr = f"{int(rp[:4])-1}{rp[4:]}"
                                        for _, pr in df.iterrows():
                                            if str(pr.get("end_date", ""))[:10] == prev_yr:
                                                pf = pr.get("fcff")
                                                if pf is not None and not (isinstance(pf, float) and math.isnan(pf)) and float(pf) != 0:
                                                    r.free_cash_flow_growth = (float(cur_fcff) - float(pf)) / abs(float(pf))
                                                break
                                    except Exception:
                                        pass
                            break
                return results
        except Exception as e:
            logger.warning("Tushare fina_indicator failed for %s: %s", ticker, e)

    return results


# ---------------------------------------------------------------------------
# Market Cap
# ---------------------------------------------------------------------------

def get_cn_market_cap(ticker: str, end_date: str) -> Optional[float]:
    ext = _get_pe_pb_mktcap(ticker, end_date)
    mc = ext.get("market_cap")
    if mc:
        return mc
    metrics = get_cn_financial_metrics(ticker, end_date, limit=1)
    if metrics and metrics[0].market_cap:
        return metrics[0].market_cap
    return None




# ---------------------------------------------------------------------------
# Line Items (financial statements via Tushare)
# ---------------------------------------------------------------------------

# Mapping from agent-requested field names -> (tushare_api, tushare_field, transform_fn)
_LINE_ITEM_SOURCES = {
    # Income statement fields
    "revenue": ("income", "revenue"),
    "net_income": ("income", "n_income"),
    "operating_income": ("income", "operate_profit"),
    "ebit": ("income", "ebit"),
    "interest_expense": ("income", "interest_expense"),
    "earnings_per_share": ("income", "basic_eps"),
    "gross_profit": ("income", None),  # computed: revenue - total_cogs
    "depreciation_and_amortization": ("income", None),  # computed: ebitda - ebit
    # Balance sheet fields
    "total_assets": ("balancesheet", "total_assets"),
    "total_liabilities": ("balancesheet", "total_liab"),
    "current_assets": ("balancesheet", "total_cur_assets"),
    "current_liabilities": ("balancesheet", "total_cur_liab"),
    "book_value_per_share": ("balancesheet", None),  # computed: equity / shares
    "shareholders_equity": ("balancesheet", "total_hldr_eqy_inc_min_int"),
    "outstanding_shares": ("balancesheet", None),  # needs daily_basic
    "working_capital": ("balancesheet", None),  # computed: current_assets - current_liabilities
    # Cash flow fields
    "free_cash_flow": ("cashflow", None),  # computed: operating_cf - capex
    "capital_expenditure": ("cashflow", "c_pay_acq_const_fiolta"),
    "dividends_and_other_cash_distributions": ("cashflow", "div_proc_pay"),
    # Additional fields needed by Aswath Damodaran & Phil Fisher agents
    "total_debt": ("balancesheet", "total_liab"),
    "research_and_development": ("income", "rd_exp"),
    "cash_and_equivalents": ("balancesheet", "money_cap"),
}


def _fetch_tushare_statement(pro, api_name: str, ts_code: str, end_date: str, limit: int):
    """Fetch a single Tushare financial statement."""
    import pandas as pd
    try:
        if api_name == "income":
            return _cached_tushare_call('income', ts_code=ts_code, end_date=end_date, limit=limit)
        elif api_name == "balancesheet":
            return _cached_tushare_call('balancesheet', ts_code=ts_code, end_date=end_date, limit=limit)
        elif api_name == "cashflow":
            return _cached_tushare_call('cashflow', ts_code=ts_code, end_date=end_date, limit=limit)
    except Exception as e:
        logger.warning("Tushare %s failed for %s: %s", api_name, ts_code, e)
    return pd.DataFrame()


def get_cn_line_items(
    ticker: str,
    line_items: list[str],
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
) -> list[LineItem]:
    """Fetch financial line items for CN A-share via Tushare."""
    # Check session cache first
    store = _get_session_store(ticker, end_date)
    if store and store.get("line_items"):
        dfs = store["line_items"]
        shares_info = {}
        pro = _get_tushare()
        if pro:
            try:
                _, ts_code = _normalize_cn_ticker(ticker)
                clean_end = end_date.replace("-", "")
                df_basic = pro.daily_basic(ts_code=ts_code, trade_date=clean_end, fields="ts_code,trade_date,total_share")
                if df_basic is not None and not df_basic.empty:
                    total_shares = float(df_basic.iloc[0].get("total_share", 0))
                    if total_shares > 0:
                        shares_info["default"] = total_shares * 1e4
            except Exception:
                pass
        
        merged = {}
        for api_name, df in dfs.items():
            for _, row in df.iterrows():
                ed = str(row.get("end_date", str(row.get("f_ann_date", ""))))[:10]
                if ed not in merged:
                    merged[ed] = {}
                for col in row.index:
                    val = row[col]
                    if hasattr(val, "item"):
                        val = val.item()
                    merged[ed][col] = val
        
        results = []
        sorted_dates = sorted(merged.keys(), reverse=True)[:limit]
        for ed in sorted_dates:
            row_data = merged[ed]
            ebitda = row_data.get("ebitda")
            ebit = row_data.get("ebit")
            depreciation_and_amortization = (float(ebitda) - float(ebit)) if ebitda is not None and ebit is not None else None
            revenue = row_data.get("revenue")
            total_cogs = row_data.get("total_cogs")
            gross_profit = (float(revenue) - float(total_cogs)) if revenue is not None and total_cogs is not None else None
            cur_assets = row_data.get("total_cur_assets")
            cur_liab = row_data.get("total_cur_liab")
            working_capital = (float(cur_assets) - float(cur_liab)) if cur_assets is not None and cur_liab is not None else None
            op_cf = row_data.get("n_cashflow_act")
            capex = row_data.get("c_pay_acq_const_fiolta")
            free_cash_flow = (float(op_cf) - abs(float(capex))) if op_cf is not None and capex is not None else None
            equity = row_data.get("total_hldr_eqy_inc_min_int")
            total_share_raw = row_data.get("total_share")
            shares = shares_info.get(ed, shares_info.get("default"))
            if shares is None and total_share_raw is not None:
                shares = float(total_share_raw) * 1e4
            book_value_per_share = (float(equity) / shares) if equity is not None and shares and shares > 0 else None
            outstanding_shares = shares
            kwargs = {"ticker": ticker, "report_period": ed, "period": period, "currency": "CNY"}
            for li in line_items:
                if li == "depreciation_and_amortization":
                    kwargs[li] = depreciation_and_amortization
                elif li == "gross_profit":
                    kwargs[li] = gross_profit
                elif li == "working_capital":
                    kwargs[li] = working_capital
                elif li == "free_cash_flow":
                    kwargs[li] = free_cash_flow
                elif li == "book_value_per_share":
                    kwargs[li] = book_value_per_share
                elif li == "shareholders_equity":
                    kwargs[li] = equity
                elif li == "research_and_development":
                    kwargs[li] = float(row_data["rd_exp"]) if row_data.get("rd_exp") is not None else None
                elif li == "cash_and_equivalents":
                    kwargs[li] = float(row_data["money_cap"]) if row_data.get("money_cap") is not None else None
                elif li == "total_debt":
                    kwargs[li] = float(row_data["total_liab"]) if row_data.get("total_liab") is not None else None
                elif li == "operating_margin":
                    op_inc = row_data.get("operate_profit")
                    rev = row_data.get("revenue")
                    kwargs[li] = float(op_inc) / float(rev) if op_inc and rev and float(rev) != 0 else None
                elif li == "gross_margin":
                    rev2 = row_data.get("revenue")
                    cogs = row_data.get("total_cogs")
                    kwargs[li] = (float(rev2) - float(cogs)) / float(rev2) if rev2 and cogs and float(rev2) != 0 else None
                elif li == "outstanding_shares":
                    kwargs[li] = outstanding_shares
                elif li in _LINE_ITEM_SOURCES:
                    _, ts_field = _LINE_ITEM_SOURCES[li]
                    if ts_field and ts_field in row_data:
                        val = row_data[ts_field]
                        kwargs[li] = float(val) if val is not None else None
            for li in line_items:
                if li not in kwargs:
                    kwargs[li] = None
            results.append(LineItem(**kwargs))
        return results

    pro = _get_tushare()
    if pro is None:
        return []

    _, ts_code = _normalize_cn_ticker(ticker)
    clean_end = end_date.replace("-", "")

    # Determine which Tushare APIs we need
    needed_apis = set()
    for li in line_items:
        if li in _LINE_ITEM_SOURCES:
            api_name, _ = _LINE_ITEM_SOURCES[li]
            needed_apis.add(api_name)

    # Default: always fetch all three for comprehensive data
    if not needed_apis:
        needed_apis = {"income", "balancesheet", "cashflow"}

    # Fetch dataframes
    dfs = {}
    for api_name in needed_apis:
        df = _fetch_tushare_statement(pro, api_name, ts_code, clean_end, limit)
        if df is not None and not df.empty:
            dfs[api_name] = df

    if not dfs:
        return []

    # Also try to get shares outstanding for per-share calculations
    shares_info = {}
    try:
        df_basic = pro.daily_basic(ts_code=ts_code, trade_date=clean_end, fields="ts_code,trade_date,total_share")
        if df_basic is not None and not df_basic.empty:
            total_shares = float(df_basic.iloc[0].get("total_share", 0))
            if total_shares > 0:
                shares_info["default"] = total_shares * 1e4  # total_share is in 10k
    except Exception:
        pass

    # Merge all statements by end_date
    # Build a dict keyed by end_date
    merged = {}
    for api_name, df in dfs.items():
        for _, row in df.iterrows():
            ed = str(row.get("end_date", str(row.get("f_ann_date", ""))))[:10]
            if ed not in merged:
                merged[ed] = {}
            for col in row.index:
                val = row[col]
                # Convert numpy types
                if hasattr(val, "item"):
                    val = val.item()
                merged[ed][col] = val

    # Build LineItem objects
    results = []
    sorted_dates = sorted(merged.keys(), reverse=True)[:limit]

    for ed in sorted_dates:
        row_data = merged[ed]

        # Compute derived fields
        ebitda = row_data.get("ebitda")
        ebit = row_data.get("ebit")
        depreciation_and_amortization = (float(ebitda) - float(ebit)) if ebitda is not None and ebit is not None else None

        revenue = row_data.get("revenue")
        total_cogs = row_data.get("total_cogs")
        gross_profit = (float(revenue) - float(total_cogs)) if revenue is not None and total_cogs is not None else None

        cur_assets = row_data.get("total_cur_assets")
        cur_liab = row_data.get("total_cur_liab")
        working_capital = (float(cur_assets) - float(cur_liab)) if cur_assets is not None and cur_liab is not None else None

        op_cf = row_data.get("n_cashflow_act")
        capex = row_data.get("c_pay_acq_const_fiolta")
        free_cash_flow = (float(op_cf) - abs(float(capex))) if op_cf is not None and capex is not None else None

        equity = row_data.get("total_hldr_eqy_inc_min_int")
        total_share_raw = row_data.get("total_share")
        shares = shares_info.get(ed, shares_info.get("default"))
        if shares is None and total_share_raw is not None:
            shares = float(total_share_raw) * 1e4

        book_value_per_share = (float(equity) / shares) if equity is not None and shares and shares > 0 else None
        outstanding_shares = shares

        # Build base kwargs
        kwargs = {
            "ticker": ticker,
            "report_period": ed,
            "period": period,
            "currency": "CNY",
        }

        # Map all Tushare fields to the requested line item names
        for li in line_items:
            if li == "depreciation_and_amortization":
                kwargs[li] = depreciation_and_amortization
            elif li == "gross_profit":
                kwargs[li] = gross_profit
            elif li == "working_capital":
                kwargs[li] = working_capital
            elif li == "free_cash_flow":
                kwargs[li] = free_cash_flow
            elif li == "book_value_per_share":
                kwargs[li] = book_value_per_share
            elif li == "shareholders_equity":
                kwargs[li] = equity
            elif li == "outstanding_shares":
                kwargs[li] = outstanding_shares
            elif li in _LINE_ITEM_SOURCES:
                _, ts_field = _LINE_ITEM_SOURCES[li]
                if ts_field and ts_field in row_data:
                    val = row_data[ts_field]
                    kwargs[li] = float(val) if val is not None else None

        # Handle computed metrics requested as line items
        for li in line_items:
            if li == "operating_margin":
                op_inc = row_data.get("operate_profit")
                rev = row_data.get("revenue")
                kwargs[li] = float(op_inc) / float(rev) if op_inc and rev and float(rev) != 0 else None
            elif li == "gross_margin":
                rev2 = row_data.get("revenue")
                cogs = row_data.get("total_cogs")
                if rev2 and cogs and float(rev2) != 0:
                    kwargs[li] = (float(rev2) - float(cogs)) / float(rev2)
                else:
                    kwargs[li] = None

        # Ensure all requested fields are present (even if None) to avoid AttributeError
        for li in line_items:
            if li not in kwargs:
                kwargs[li] = None

        results.append(LineItem(**kwargs))

    return results

# ---------------------------------------------------------------------------
# Company News (AKShare)
# ---------------------------------------------------------------------------


def _quick_sentiment(title: str):
    """Quick rule-based sentiment detection for Chinese financial news titles."""
    if not title:
        return None
    positive_words = ["增长", "上涨", "利好", "突破", "创新", "超预期", "净利", "业绩", "分红", "回购", "收益"]
    negative_words = ["下跌", "亏损", "爆雷", "警示", "违规", "质疑", "风险", "被ST", "财务造假", "利空"]
    for w in positive_words:
        if w in title:
            return "positive"
    for w in negative_words:
        if w in title:
            return "negative"
    return "neutral"



# ---------------------------------------------------------------------------
# Eastmoney (a-stock-data skill) fallback APIs
# ---------------------------------------------------------------------------

import urllib.parse as _urlparse

def _get_em_financial(ticker: str, report_type: str = "balance", limit: int = 10) -> list[dict]:
    """Fetch financial statements from Eastmoney (a-stock-data skill fallback).
    report_type: "balance" | "income" | "cashflow"
    """
    pure_code, _ = _normalize_cn_ticker(ticker)
    market = "SH" if pure_code.startswith("6") else "SZ"
    
    report_map = {
        "balance": "FRS_BALANCE",
        "income": "FRS_INCOME",
        "cashflow": "FRS_CASHFLOW",
    }
    rpt = report_map.get(report_type, "FRS_BALANCE")
    
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": f"RPT_DMSK_FN_MAININDICATOR",
        "columns": "ALL",
        "filter": f'(SECURITY_CODE="{pure_code}")(SECURITY_TYPE_CODE="{market}")',
        "pageNumber": "1",
        "pageSize": str(limit),
        "sortTypes": "-1",
        "sortColumns": "REPORT_DATE",
        "source": "WEB",
        "client": "WEB",
    }
    
    try:
        resp = _requests.get(url, params=params, timeout=10, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://data.eastmoney.com/",
        })
        data = resp.json()
        if data.get("success") and data.get("result") and data["result"].get("data"):
            return data["result"]["data"]
    except Exception as e:
        logger.warning("Eastmoney %s API failed for %s: %s", report_type, ticker, e)
    return []


def _get_em_news(ticker: str, limit: int = 50) -> list[dict]:
    """Fetch stock news from Eastmoney (a-stock-data skill fallback)."""
    pure_code, _ = _normalize_cn_ticker(ticker)
    market = "1" if pure_code.startswith("6") else "0"
    
    url = "https://search-api-web.eastmoney.com/search/jsonp"
    params = {
        "cb": "jQuery",
        "param": _urlparse.quote(f'uid=&keyword={pure_code}&type=["8196","8197","8198","8199"]&client=PC&pageIndex=1&pageSize={limit}'),
    }
    
    try:
        resp = _requests.get(url, params=params, timeout=10, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://so.eastmoney.com/",
        })
        # Response is JSONP: jQuery(...)
        text = resp.text
        json_str = text[text.index("(") + 1:text.rindex(")")]
        data = json.loads(json_str)
        if data.get("Data"):
            return data["Data"]
    except Exception as e:
        logger.warning("Eastmoney news API failed for %s: %s", ticker, e)
    return []


def get_cn_company_news(
    ticker: str,
    end_date: str,
    start_date: Optional[str] = None,
    limit: int = 100,
) -> list[CompanyNews]:
    """Fetch company news. Priority: Tavily search > AKShare fallback."""
    pure_code, _ = _normalize_cn_ticker(ticker)
    results = []

    # 1) Try Tavily search first (more reliable for A-shares)
    tavily_key = os.environ.get("TAVILY_API_KEY", "")
    if tavily_key:
        try:
            from tavily import TavilyClient
            client = TavilyClient(api_key=tavily_key)
            query = f"{ticker} stock news latest"
            response = client.search(query, max_results=min(limit, 20), search_depth="advanced")
            for r in response.get("results", []):
                title = r.get("title", "")
                if not title:
                    continue
                news_date = r.get("published_date", "")[:10] if r.get("published_date") else end_date[:10]
                if end_date and news_date > end_date:
                    continue
                if start_date and news_date < start_date:
                    continue
                results.append(CompanyNews(
                    ticker=ticker,
                    title=title,
                    source="Tavily",
                    date=news_date,
                    url=r.get("url", ""),
                    sentiment=_quick_sentiment(title),
                ))
        except Exception as e:
            logger.warning("Tavily news search failed for %s: %s", ticker, e)

    # 2) Fallback: AKShare (may need proxy in mainland China)
    if not results:
        try:
            import akshare as ak
            df = ak.stock_news_em(symbol=pure_code)
            if df is not None and not df.empty:
                col_mapping = {}
                for col in df.columns:
                    if "时间" in col or "date" in col.lower() or "time" in col.lower():
                        col_mapping["date"] = col
                    elif "标题" in col or "title" in col.lower():
                        col_mapping["title"] = col
                    elif "来源" in col or "source" in col.lower():
                        col_mapping["source"] = col
                    elif "链接" in col or "url" in col.lower():
                        col_mapping["url"] = col
                for _, row in df.head(limit).iterrows():
                    title = str(row.get(col_mapping.get("title", ""), ""))
                    if not title or title == "nan":
                        continue
                    news_date = str(row.get(col_mapping.get("date", ""), ""))[:10]
                    if end_date and news_date > end_date:
                        continue
                    if start_date and news_date < start_date:
                        continue
                    results.append(CompanyNews(
                        ticker=ticker,
                        title=title,
                        source=str(row.get(col_mapping.get("source", ""), "")),
                        date=news_date,
                        url=str(row.get(col_mapping.get("url", ""), "")),
                        sentiment=_quick_sentiment(title),
                    ))
        except Exception as e:
            logger.warning("AKShare news failed for %s: %s", ticker, e)

    # 3) Last fallback: Eastmoney news (a-stock-data skill)
    if not results:
        try:
            em_news = _get_em_news(ticker, limit)
            for item in em_news:
                title = item.get("Title", "")
                if not title:
                    continue
                news_date = item.get("ShowTime", "")[:10] if item.get("ShowTime") else end_date[:10]
                if end_date and news_date > end_date:
                    continue
                if start_date and news_date < start_date:
                    continue
                results.append(CompanyNews(
                    ticker=ticker,
                    title=title,
                    source=str(item.get("SourceName", "Eastmoney")),
                    date=news_date,
                    url=item.get("Url", ""),
                    sentiment=_quick_sentiment(title),
                ))
        except Exception as e:
            logger.warning("Eastmoney news failed for %s: %s", ticker, e)

    return results



def _get_cn_insider_trades_eastmoney(
    ticker: str,
    end_date: str,
    start_date: Optional[str] = None,
    limit: int = 1000,
) -> list[InsiderTrade]:
    """Fetch insider/executive holding changes from Eastmoney datacenter."""
    import requests as _requests
    _, ts_code = _normalize_cn_ticker(ticker)
    pure_code, _ = _normalize_cn_ticker(ticker)
    
    # Eastmoney datacenter API
    url = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
    params = {
        "reportName": "RPTA_WEB_HOLDCHANGE",
        "columns": "ALL",
        "filter": f'(SECURITY_CODE="{pure_code}")',
        "pageNumber": "1",
        "pageSize": str(min(limit, 100)),
        "sortColumns": "CHANGE_DATE",
        "sortTypes": "-1",
        "source": "WEB",
        "client": "WEB",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    r = _requests.get(url, params=params, headers=headers, timeout=15)
    data = r.json()
    result = data.get("result") or {}
    rows = result.get("data") or []
    if not rows:
        return []
    
    results = []
    for row in rows:
        change_date = str(row.get("CHANGE_DATE", ""))[:10]
        if not change_date:
            continue
        if end_date and change_date > end_date:
            continue
        if start_date and change_date < start_date:
            continue
        
        name = row.get("HOLDER_NAME", "")
        position = row.get("POSITION", "")  # e.g. ??/??/??
        change_vol = row.get("CHANGE_VOL")
        change_ratio = row.get("CHANGE_RATIO")
        avg_price = row.get("AVG_PRICE")
        
        shares = None
        value = None
        if change_vol is not None:
            try:
                shares = float(change_vol)
                if avg_price is not None:
                    value = shares * float(avg_price)
            except (ValueError, TypeError):
                pass
        
        results.append(InsiderTrade(
            ticker=ticker,
            issuer=None,
            name=str(name) if name else None,
            title=f"{position}: {name}" if position else str(name) if name else None,
            is_board_director=(str(position) in ("??", "??", "??", "????")),
            transaction_date=change_date,
            transaction_shares=shares,
            transaction_price_per_share=float(avg_price) if avg_price is not None else None,
            transaction_value=value,
            shares_owned_before_transaction=None,
            shares_owned_after_transaction=None,
            security_title=None,
            filing_date=change_date,
        ))
    return results


def get_cn_insider_trades(
    ticker: str,
    end_date: str,
    start_date: Optional[str] = None,
    limit: int = 1000,
) -> list[InsiderTrade]:
    """Fetch A-share insider/executive trades.
    Primary: Tushare stk_holdertrade (structured).
    Fallback: Tavily web search.
    
    "内部人" refers to directors, supervisors, senior management (董监高)
    and shareholders holding >5% (大股东) as defined by CSRC regulations.
    """
    _, ts_code = _normalize_cn_ticker(ticker)
    results = []

    # 1) Try Tushare stk_holdertrade (structured insider trade data)
    pro = _get_tushare()
    if pro is not None:
        try:
            clean_end = end_date.replace("-", "")
            clean_start = (start_date or "20200101").replace("-", "")
            df = pro.stk_holdertrade(ts_code=ts_code, start_date=clean_start, end_date=clean_end)
            if df is not None and not df.empty:
                for _, row in df.head(limit).iterrows():
                    ann_date = str(row.get("ann_date", ""))[:10]
                    holder_name = str(row.get("holder_name", ""))
                    holder_type = str(row.get("holder_type", ""))  # 高管/个人/公司
                    change_vol = row.get("change_vol")
                    avg_price = row.get("avg_price")
                    in_vol = row.get("in_vol")
                    out_vol = row.get("out_vol")

                    shares = None
                    if change_vol is not None and not (isinstance(change_vol, float) and math.isnan(change_vol)):
                        shares = float(change_vol)
                    elif in_vol is not None and out_vol is not None:
                        in_v = float(in_vol) if not (isinstance(in_vol, float) and math.isnan(in_vol)) else 0
                        out_v = float(out_vol) if not (isinstance(out_vol, float) and math.isnan(out_vol)) else 0
                        shares = in_v - out_v

                    value = None
                    if shares is not None and avg_price is not None and not (isinstance(avg_price, float) and math.isnan(avg_price)):
                        value = shares * float(avg_price)

                    results.append(InsiderTrade(
                        ticker=ticker,
                        issuer=None,
                        name=holder_name if holder_name else None,
                        title=f"{holder_type}: {holder_name}" if holder_type else None,
                        is_board_director=(holder_type == "高管"),
                        transaction_date=ann_date,
                        transaction_shares=shares,
                        transaction_price_per_share=float(avg_price) if avg_price is not None and not (isinstance(avg_price, float) and math.isnan(avg_price)) else None,
                        transaction_value=value,
                        shares_owned_before_transaction=None,
                        shares_owned_after_transaction=None,
                        security_title=None,
                        filing_date=ann_date,
                    ))
                if results:
                    return results
        except Exception as e:
            logger.warning("Tushare stk_holdertrade failed for %s: %s", ticker, e)

    # 2) Fallback: Eastmoney datacenter (executive/director holding changes)
    try:
        em_results = _get_cn_insider_trades_eastmoney(ticker, end_date, start_date, limit)
        if em_results:
            return em_results
    except Exception as e:
        logger.warning("Eastmoney insider trades failed for %s: %s", ticker, e)

    # 3) Fallback: Tavily web search
    tavily_key = os.environ.get("TAVILY_API_KEY", "")
    if not tavily_key:
        return results
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=tavily_key)
        query = f"{ticker} 股票 内幕交易 OR 大股东增持 OR 大股东减持 OR 高管增持"
        response = client.search(query, max_results=min(limit, 10), search_depth="advanced")
        for r in response.get("results", []):
            title = r.get("title", "")
            date = r.get("published_date", end_date[:10])[:10] if r.get("published_date") else end_date[:10]
            if end_date and date > end_date:
                continue
            if start_date and date < start_date:
                continue
            results.append(InsiderTrade(
                ticker=ticker,
                issuer=None,
                name=None,
                title=title,
                is_board_director=None,
                transaction_date=date,
                transaction_shares=None,
                transaction_price_per_share=None,
                transaction_value=None,
                shares_owned_before_transaction=None,
                shares_owned_after_transaction=None,
                security_title=None,
                filing_date=date,
            ))
    except Exception as e:
        logger.warning("Tavily insider search failed for %s: %s", ticker, e)
    return results


def get_cn_company_facts(ticker: str) -> Optional[CompanyFacts]:
    _, ts_code = _normalize_cn_ticker(ticker)

    pro = _get_tushare()
    if pro is not None:
        try:
            df = _cached_tushare_call("stock_basic", ts_code=ts_code, fields="ts_code,name,industry,list_date")
            if df is not None and not df.empty:
                r = df.iloc[0]
                return CompanyFacts(
                    ticker=ticker,
                    name=str(r.get("name", "")),
                    industry=str(r.get("industry", "")),
                    listing_date=str(r.get("list_date", "")),
                )
        except Exception as e:
            logger.warning("Tushare stock_basic failed: %s", e)

    return None
