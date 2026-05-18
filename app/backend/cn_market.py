from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import tushare as ts
from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = ROOT.parents[1]
OPENCLAW_ROOT = WORKSPACE_ROOT.parents[0]
REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


@dataclass
class InstrumentInfo:
    code: str
    ts_code: str
    name: str
    instrument_type: str
    market: str
    industry: str | None = None
    management: str | None = None


@dataclass
class AnalysisResult:
    request_id: str
    instrument_type: str
    code: str
    ts_code: str
    name: str
    start_date: str
    end_date: str
    latest_price: float
    latest_change_pct: float
    period_return_pct: float
    volatility_pct: float
    max_drawdown_pct: float
    signal: str
    confidence: int
    summary: str
    reasoning: dict[str, Any]
    markdown_path: str
    json_path: str


def _load_env_value(key: str) -> str | None:
    candidates = [ROOT / ".env", OPENCLAW_ROOT / ".env"]
    for env_path in candidates:
        if env_path.exists():
            values = dotenv_values(env_path)
            value = values.get(key)
            if value:
                return str(value).strip()
    value = os.getenv(key)
    return value.strip() if value else None


def _extract_deepseek_key() -> str | None:
    candidates = [ROOT / "secrets" / "credentials.md", WORKSPACE_ROOT / "secrets" / "credentials.md"]
    patterns = [
        r"DEEPSEEK_API_KEY\s*[:=]\s*([A-Za-z0-9_\-]+)",
        r"(sk-[A-Za-z0-9]{20,})",
    ]
    for path in candidates:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
    value = os.getenv("DEEPSEEK_API_KEY")
    return value.strip() if value else None


def ensure_project_env() -> dict[str, str]:
    env_path = ROOT / ".env"
    existing = dotenv_values(env_path) if env_path.exists() else {}
    tushare_token = existing.get("TUSHARE_TOKEN") or _load_env_value("TUSHARE_TOKEN") or ""
    deepseek_key = existing.get("DEEPSEEK_API_KEY") or _extract_deepseek_key() or ""
    model = existing.get("DEFAULT_MODEL") or "deepseek-chat"
    content = "\n".join([
        f"TUSHARE_TOKEN={tushare_token}",
        f"DEEPSEEK_API_KEY={deepseek_key}",
        "DEFAULT_MODEL_PROVIDER=DeepSeek",
        f"DEFAULT_MODEL={model}",
        "REPORT_OUTPUT_DIR=reports",
        "CN_MARKET_ENABLED=true",
        "",
    ])
    env_path.write_text(content, encoding="utf-8")
    return {"TUSHARE_TOKEN": tushare_token, "DEEPSEEK_API_KEY": deepseek_key, "DEFAULT_MODEL": model}


def _get_pro_client():
    token = _load_env_value("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN 未配置")
    ts.set_token(token)
    return ts.pro_api(token)


def _normalize_dates(start_date: str, end_date: str) -> tuple[str, str]:
    return start_date.replace("-", ""), end_date.replace("-", "")


def _resolve_stock(code: str, pro) -> InstrumentInfo:
    normalized = code.upper().strip()
    if "." in normalized:
        ts_code = normalized
    elif normalized.startswith(("6", "9")):
        ts_code = f"{normalized}.SH"
    else:
        ts_code = f"{normalized}.SZ"
    df = pro.stock_basic(ts_code=ts_code, fields="ts_code,symbol,name,industry,market")
    if df is None or df.empty:
        raise RuntimeError(f"未找到股票代码 {code}")
    row = df.iloc[0]
    return InstrumentInfo(
        code=str(row.get("symbol") or normalized),
        ts_code=str(row["ts_code"]),
        name=str(row.get("name") or normalized),
        instrument_type="stock",
        market=str(row.get("market") or "CN"),
        industry=(str(row.get("industry")) if row.get("industry") else None),
    )


def _resolve_fund(code: str, pro) -> InstrumentInfo:
    normalized = code.upper().strip()
    df = pro.fund_basic(market="E", status="L")
    if df is None or df.empty:
        raise RuntimeError("基金列表为空")
    hit = df[(df["ts_code"].astype(str).str.upper() == normalized) | (df["ts_code"].astype(str).str.startswith(normalized.split('.')[0]))]
    if hit.empty:
        raise RuntimeError(f"未找到基金代码 {code}")
    row = hit.iloc[0]
    return InstrumentInfo(
        code=str(row["ts_code"]).split(".")[0],
        ts_code=str(row["ts_code"]),
        name=str(row.get("name") or code),
        instrument_type="fund",
        market=str(row.get("market") or "E"),
        management=(str(row.get("management")) if row.get("management") else None),
    )


def _load_stock_prices(ts_code: str, start_date: str, end_date: str, pro):
    start_compact, end_compact = _normalize_dates(start_date, end_date)
    df = pro.daily(ts_code=ts_code, start_date=start_compact, end_date=end_compact)
    if df is None or df.empty:
        raise RuntimeError(f"股票 {ts_code} 无行情数据")
    return df.sort_values("trade_date").reset_index(drop=True)


def _load_fund_prices(ts_code: str, start_date: str, end_date: str, pro):
    start_compact, end_compact = _normalize_dates(start_date, end_date)
    df = pro.fund_nav(ts_code=ts_code)
    if df is None or df.empty:
        raise RuntimeError(f"基金 {ts_code} 无净值数据")
    date_col = "nav_date" if "nav_date" in df.columns else "end_date"
    value_col = "adj_nav" if "adj_nav" in df.columns else "unit_nav"
    df = df[df[date_col].astype(str).between(start_compact, end_compact)].copy()
    if df.empty:
        raise RuntimeError(f"基金 {ts_code} 在区间内无净值数据")
    df = df.sort_values(date_col).reset_index(drop=True)
    df["close"] = df[value_col].astype(float)
    df["pct_chg"] = df["close"].pct_change().fillna(0.0) * 100
    df["trade_date"] = df[date_col]
    return df


def _compute_metrics(df, instrument_type: str) -> dict[str, float | str | int]:
    closes = df["close"].astype(float)
    returns = closes.pct_change().dropna()
    latest_price = round(float(closes.iloc[-1]), 4)
    latest_change_pct = round(float(df["pct_chg"].iloc[-1]), 2)
    period_return_pct = round(float((closes.iloc[-1] / closes.iloc[0] - 1) * 100), 2)
    volatility_pct = round(float(returns.std() * (252 ** 0.5) * 100), 2) if not returns.empty else 0.0
    running_max = closes.cummax()
    drawdown = (closes / running_max - 1.0) * 100
    max_drawdown_pct = round(float(drawdown.min()), 2)
    signal = "bullish" if period_return_pct >= 5 else "neutral" if period_return_pct >= -5 else "bearish"
    confidence = min(90, max(55, int(abs(period_return_pct) + abs(latest_change_pct) + 50)))
    summary = f"{instrument_type} {signal}，区间收益 {period_return_pct}% ，最新变动 {latest_change_pct}% 。"
    return {
        "latest_price": latest_price,
        "latest_change_pct": latest_change_pct,
        "period_return_pct": period_return_pct,
        "volatility_pct": volatility_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "signal": signal,
        "confidence": confidence,
        "summary": summary,
    }


def write_reports(payload: dict[str, Any]) -> tuple[str, str]:
    request_id = payload["request_id"]
    md_path = REPORTS_DIR / f"{request_id}.md"
    json_path = REPORTS_DIR / f"{request_id}.json"
    markdown = f"""# AI Hedge Fund CN Report

- Request ID: {payload['request_id']}
- Type: {payload['instrument_type']}
- Code: {payload['code']}
- Tushare Code: {payload['ts_code']}
- Name: {payload['name']}
- Period: {payload['start_date']} to {payload['end_date']}
- Latest Price/NAV: {payload['latest_price']}
- Latest Change: {payload['latest_change_pct']}%
- Period Return: {payload['period_return_pct']}%
- Volatility: {payload['volatility_pct']}%
- Max Drawdown: {payload['max_drawdown_pct']}%
- Signal: {payload['signal']}
- Confidence: {payload['confidence']}

## Summary
{payload['summary']}

## Reasoning
```json
{json.dumps(payload['reasoning'], ensure_ascii=False, indent=2)}
```
"""
    md_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(md_path), str(json_path)


def analyze_instrument(code: str, instrument_type: str, start_date: str, end_date: str) -> AnalysisResult:
    pro = _get_pro_client()
    if instrument_type == "fund":
        info = _resolve_fund(code, pro)
        df = _load_fund_prices(info.ts_code, start_date, end_date, pro)
    else:
        info = _resolve_stock(code, pro)
        df = _load_stock_prices(info.ts_code, start_date, end_date, pro)
    metrics = _compute_metrics(df, instrument_type)
    request_id = f"{instrument_type}-{info.code}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    reasoning = {
        "instrument": asdict(info),
        "sample_size": int(len(df)),
        "latest_trade_date": str(df["trade_date"].iloc[-1]),
        "provider": "tushare",
        "llm_provider": "deepseek",
        "llm_model": _load_env_value("DEFAULT_MODEL") or "deepseek-chat",
    }
    payload = {
        "request_id": request_id,
        "instrument_type": instrument_type,
        "code": info.code,
        "ts_code": info.ts_code,
        "name": info.name,
        "start_date": start_date,
        "end_date": end_date,
        **metrics,
        "reasoning": reasoning,
    }
    markdown_path, json_path = write_reports(payload)
    return AnalysisResult(markdown_path=markdown_path, json_path=json_path, **payload)
