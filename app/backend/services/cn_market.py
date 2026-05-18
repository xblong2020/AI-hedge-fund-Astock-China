from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import tushare as ts
from dotenv import dotenv_values

ROOT_ENV = Path(r"C:\Users\Administrator\.openclaw\.env")
WORKSPACE = Path(r"C:\Users\Administrator\.openclaw\workspace")
CREDENTIALS = WORKSPACE / "secrets" / "credentials.md"
REPORTS_DIR = WORKSPACE / "projects" / "ai-hedge-fund-cn" / "reports"


@dataclass
class CNAsset:
    symbol: str
    market: str
    ts_code: str
    name: str | None = None


class CNConfigError(RuntimeError):
    pass


class TushareProvider:
    def __init__(self) -> None:
        token = self._load_tushare_token()
        self.pro = ts.pro_api(token)

    @staticmethod
    def _load_tushare_token() -> str:
        values = dotenv_values(ROOT_ENV)
        token = values.get("TUSHARE_TOKEN") or os.getenv("TUSHARE_TOKEN")
        if not token:
            raise CNConfigError("TUSHARE_TOKEN 缺失")
        return str(token).strip().strip('"').strip("'")

    def resolve_asset(self, symbol: str, market: str) -> CNAsset:
        market = market.lower().strip()
        if market == "stock":
            ts_code = self._normalize_stock_code(symbol)
            base = self.pro.stock_basic(ts_code=ts_code, fields="ts_code,name")
            name = None if base.empty else str(base.iloc[0].get("name") or "")
            return CNAsset(symbol=symbol, market=market, ts_code=ts_code, name=name or None)
        if market == "fund":
            ts_code = self._normalize_fund_code(symbol)
            base = self.pro.fund_basic(ts_code=ts_code, market='E')
            name = None if base.empty else str(base.iloc[0].get("name") or "")
            return CNAsset(symbol=symbol, market=market, ts_code=ts_code, name=name or None)
        raise ValueError(f"不支持的 market: {market}")

    def get_price_series(self, asset: CNAsset, start_date: str, end_date: str) -> list[dict[str, Any]]:
        start = start_date.replace("-", "")
        end = end_date.replace("-", "")
        if asset.market == "stock":
            df = self.pro.daily(ts_code=asset.ts_code, start_date=start, end_date=end)
            if df.empty:
                raise RuntimeError(f"未获取到股票行情: {asset.ts_code}")
            rows = []
            for row in df.sort_values("trade_date").to_dict(orient="records"):
                rows.append({
                    "date": self._fmt_date(row.get("trade_date")),
                    "open": self._to_float(row.get("open")),
                    "high": self._to_float(row.get("high")),
                    "low": self._to_float(row.get("low")),
                    "close": self._to_float(row.get("close")),
                    "volume": self._to_float(row.get("vol")),
                    "amount": self._to_float(row.get("amount")),
                    "pct_chg": self._to_float(row.get("pct_chg")),
                })
            return rows
        df = self.pro.fund_nav(ts_code=asset.ts_code)
        if df.empty:
            raise RuntimeError(f"未获取到基金净值: {asset.ts_code}")
        df["nav_date"] = df["nav_date"].astype(str)
        df = df[(df["nav_date"] >= start) & (df["nav_date"] <= end)].sort_values("nav_date")
        if df.empty:
            raise RuntimeError(f"目标日期范围内无基金净值: {asset.ts_code}")
        rows = []
        prev = None
        for row in df.to_dict(orient="records"):
            close = self._to_float(row.get("adj_nav") or row.get("unit_nav") or row.get("accum_nav"))
            pct_chg = None if prev in (None, 0) else round((close - prev) / prev * 100, 4)
            rows.append({
                "date": self._fmt_date(row.get("nav_date")),
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": None,
                "amount": None,
                "pct_chg": pct_chg,
            })
            prev = close
        return rows

    def get_latest_snapshot(self, asset: CNAsset) -> dict[str, Any]:
        if asset.market == "stock":
            daily = self.pro.daily(ts_code=asset.ts_code, start_date="20000101", end_date=datetime.now().strftime("%Y%m%d"))
            if daily.empty:
                raise RuntimeError(f"未获取到股票快照: {asset.ts_code}")
            row = daily.sort_values("trade_date", ascending=False).iloc[0].to_dict()
            return {
                "date": self._fmt_date(row.get("trade_date")),
                "close": self._to_float(row.get("close")),
                "pct_chg": self._to_float(row.get("pct_chg")),
                "amount": self._to_float(row.get("amount")),
            }
        nav = self.pro.fund_nav(ts_code=asset.ts_code)
        if nav.empty:
            raise RuntimeError(f"未获取到基金快照: {asset.ts_code}")
        row = nav.sort_values("nav_date", ascending=False).iloc[0].to_dict()
        return {
            "date": self._fmt_date(row.get("nav_date")),
            "close": self._to_float(row.get("adj_nav") or row.get("unit_nav") or row.get("accum_nav")),
            "pct_chg": None,
            "amount": None,
        }

    @staticmethod
    def _normalize_stock_code(symbol: str) -> str:
        symbol = symbol.strip().upper()
        if re.match(r"^\d{6}\.(SH|SZ|BJ)$", symbol):
            return symbol
        digits = re.sub(r"\D", "", symbol)
        if len(digits) != 6:
            raise ValueError(f"股票代码格式错误: {symbol}")
        suffix = "SH" if digits.startswith(("5", "6", "9")) else "SZ"
        return f"{digits}.{suffix}"

    @staticmethod
    def _normalize_fund_code(symbol: str) -> str:
        symbol = symbol.strip().upper()
        if re.match(r"^\d{6}\.(OF|SH|SZ)$", symbol):
            return symbol
        digits = re.sub(r"\D", "", symbol)
        if len(digits) != 6:
            raise ValueError(f"基金代码格式错误: {symbol}")
        return f"{digits}.OF"

    @staticmethod
    def _fmt_date(value: Any) -> str:
        text = str(value)
        if len(text) == 8 and text.isdigit():
            return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
        return text

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            if isinstance(value, float) and math.isnan(value):
                return None
        except Exception:
            pass
        try:
            return float(value)
        except Exception:
            return None


class DeepSeekClient:
    def __init__(self) -> None:
        self.api_key = self._load_api_key()
        self.base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    @staticmethod
    def _load_api_key() -> str:
        env_key = os.getenv("DEEPSEEK_API_KEY")
        if env_key:
            return env_key.strip()
        if not CREDENTIALS.exists():
            raise CNConfigError("DeepSeek 凭证文件缺失")
        text = CREDENTIALS.read_text(encoding="utf-8", errors="ignore")
        patterns = [
            r"DEEPSEEK_API_KEY\s*[:=]\s*([A-Za-z0-9_\-]+)",
            r"deepseek[^\n]*?sk-[A-Za-z0-9]+",
            r"(sk-[A-Za-z0-9]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                value = match.group(1) if match.groups() else match.group(0)
                return value.strip().strip('`').strip()
        raise CNConfigError("DeepSeek API Key 未找到")

    def summarize(self, payload: dict[str, Any]) -> dict[str, Any]:
        prompt = self._build_prompt(payload)
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是中国市场买方分析师，输出严格 JSON。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        with httpx.Client(timeout=120) as client:
            response = client.post(f"{self.base_url}/chat/completions", headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)

    @staticmethod
    def _build_prompt(payload: dict[str, Any]) -> str:
        return (
            "基于以下中国市场数据，输出 JSON，字段包含 summary、signal、confidence、key_points、risks、next_step。"
            " signal 只能是 bullish/neutral/bearish。"
            f"\n数据: {json.dumps(payload, ensure_ascii=False)}"
        )


def analyze_cn_asset(symbol: str, market: str, start_date: str, end_date: str) -> dict[str, Any]:
    provider = TushareProvider()
    asset = provider.resolve_asset(symbol, market)
    series = provider.get_price_series(asset, start_date, end_date)
    latest = provider.get_latest_snapshot(asset)
    closes = [row["close"] for row in series if row.get("close") is not None]
    start_close = closes[0]
    end_close = closes[-1]
    total_return = round((end_close - start_close) / start_close * 100, 4) if start_close else None
    pct_changes = [row["pct_chg"] for row in series if row.get("pct_chg") is not None]
    avg_pct_change = round(sum(pct_changes) / len(pct_changes), 4) if pct_changes else None
    max_close = max(closes)
    min_close = min(closes)
    llm = DeepSeekClient()
    stats = {
        "symbol": symbol,
        "market": market,
        "ts_code": asset.ts_code,
        "name": asset.name,
        "start_date": start_date,
        "end_date": end_date,
        "points": len(series),
        "start_close": start_close,
        "end_close": end_close,
        "total_return_pct": total_return,
        "avg_pct_change": avg_pct_change,
        "max_close": max_close,
        "min_close": min_close,
        "latest_snapshot": latest,
        "series_tail": series[-10:],
    }
    llm_result = llm.summarize(stats)
    report = {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "provider": "tushare",
            "llm_provider": "deepseek",
            "llm_model": llm.model,
        },
        "asset": {
            "symbol": symbol,
            "market": market,
            "ts_code": asset.ts_code,
            "name": asset.name,
        },
        "stats": stats,
        "analysis": llm_result,
    }
    return report


def ensure_report_dir() -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return REPORTS_DIR


def save_report_files(report: dict[str, Any]) -> dict[str, str]:
    report_dir = ensure_report_dir()
    asset = report["asset"]
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"{asset['market']}-{asset['symbol']}-{ts}"
    json_path = report_dir / f"{base}.json"
    md_path = report_dir / f"{base}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown_report(report), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def render_markdown_report(report: dict[str, Any]) -> str:
    asset = report["asset"]
    stats = report["stats"]
    analysis = report["analysis"]
    key_points = analysis.get("key_points") or []
    risks = analysis.get("risks") or []
    lines = [
        f"# AI Hedge Fund 中国市场报告 - {asset['symbol']}",
        "",
        f"- 名称: {asset.get('name') or ''}",
        f"- 市场: {asset['market']}",
        f"- Tushare 代码: {asset['ts_code']}",
        f"- 统计区间: {stats['start_date']} ~ {stats['end_date']}",
        f"- 生成时间: {report['meta']['generated_at']}",
        "",
        "## 结论",
        "",
        f"- 信号: {analysis.get('signal')}",
        f"- 置信度: {analysis.get('confidence')}",
        f"- 摘要: {analysis.get('summary')}",
        f"- 下一步: {analysis.get('next_step')}",
        "",
        "## 关键统计",
        "",
        f"- 起始收盘/净值: {stats.get('start_close')}",
        f"- 结束收盘/净值: {stats.get('end_close')}",
        f"- 区间收益率: {stats.get('total_return_pct')}%",
        f"- 平均日变动: {stats.get('avg_pct_change')}",
        f"- 区间最高: {stats.get('max_close')}",
        f"- 区间最低: {stats.get('min_close')}",
        "",
        "## 关键观点",
        "",
    ]
    for item in key_points:
        lines.append(f"- {item}")
    lines.extend(["", "## 风险", ""])
    for item in risks:
        lines.append(f"- {item}")
    lines.extend(["", "## 最新快照", "", f"- 日期: {stats['latest_snapshot'].get('date')}", f"- 最新值: {stats['latest_snapshot'].get('close')}", f"- 涨跌幅: {stats['latest_snapshot'].get('pct_chg')}"])
    return "\n".join(lines) + "\n"
