"""Generate a detailed, beautifully styled HTML report from AI Hedge Fund results."""

import json
import os
from datetime import datetime
from typing import Optional


import json

LT = chr(60)
GT = chr(62)


# --- Chinese translation helpers ---

def _cn_agent(name: str) -> str:
    m = {
        "Warren Buffett": "沃伦·巴菲特",
        "Charlie Munger": "查理·芒格",
        "Ben Graham": "本杰明·格雷厄姆",
        "Bill Ackman": "比尔·阿克曼",
        "Cathie Wood": "凯茜·伍德",
        "Michael Burry": "迈克尔·伯里",
        "Mohnish Pabrai": "莫尼什·帕布莱",
        "Nassim Taleb": "纳西姆·塔勒布",
        "Peter Lynch": "彼得·林奇",
        "Phil Fisher": "菲利普·费雪",
        "Rakesh Jhunjhunwala": "拉克什·军军瓦拉",
        "Stanley Druckenmiller": "斯坦利·德鲁肯米勒",
        "Aswath Damodaran": "阿斯沃斯·达莫达兰",
    }
    return m.get(name, name)

def _cn_sig(sig: str) -> str:
    m = {"bullish": "看多", "bearish": "看空", "neutral": "中性"}
    return m.get(str(sig).lower(), str(sig).upper())

def _cn_action(act: str) -> str:
    m = {"buy": "买入", "sell": "卖出", "hold": "持有", "cover": "回补", "short": "做空"}
    return m.get(str(act).lower(), str(act).upper())

def _fmt_technical_reasoning(reasoning: dict) -> str:
    sections = {
        "trend_following": ("趋势跟踪", [("ADX", "adx"), ("趋势强度", "trend_strength")]),
        "mean_reversion": ("均值回归", [("Z-Score", "z_score"), ("布林带位置", "price_vs_bb"), ("RSI(14)", "rsi_14"), ("RSI(28)", "rsi_28")]),
        "momentum": ("动量", [("1月动量", "momentum_1m"), ("3月动量", "momentum_3m"), ("6月动量", "momentum_6m"), ("成交量动量", "volume_momentum")]),
        "volatility": ("波动率", [("历史波动率", "historical_volatility"), ("ATR比率", "atr_ratio")]),
        "statistical_arbitrage": ("统计套利", [("Hurst指数", "hurst_exponent"), ("偏度", "skewness"), ("峰度", "kurtosis")]),
    }
    rows = []
    for key, (label, metrics) in sections.items():
        if key in reasoning:
            sec = reasoning[key]
            sig = sec.get("signal", "neutral")
            conf = sec.get("confidence", 0)
            m = sec.get("metrics", {})
            sc = {"bullish": "#3fb950", "bearish": "#f85149", "neutral": "#d2991d"}.get(sig, "#8b949e")
            vals = ""
            for cn, en in metrics:
                v = m.get(en)
                if v is not None:
                    if isinstance(v, float):
                        v = round(v, 2)
                    vals += f"{LT}div style='font-size:0.8em;color:#8b949e;'{GT}{cn}: {LT}b{GT}{v}{LT}/b{GT}{LT}/div{GT}"
            rows.append(f"{LT}tr{GT}{LT}td style='color:#58a6ff;font-weight:600'{GT}{label}{LT}/td{GT}{LT}td{GT}{LT}span style='color:{sc};font-weight:700'{GT}{_cn_sig(sig)}{LT}/span{GT}{LT}/td{GT}{LT}td{GT}{float(conf):.0f}%{LT}/td{GT}{LT}td{GT}{vals}{LT}/td{GT}{LT}/tr{GT}")
    if not rows:
        return json.dumps(reasoning, ensure_ascii=False, indent=2)
    hdr = f"{LT}tr style='border-bottom:1px solid #21262d'{GT}{LT}th style='text-align:left;padding:6px;color:#8b949e'{GT}指标{LT}/th{GT}{LT}th style='text-align:left;padding:6px;color:#8b949e'{GT}信号{LT}/th{GT}{LT}th style='text-align:left;padding:6px;color:#8b949e'{GT}置信{LT}/th{GT}{LT}th style='text-align:left;padding:6px;color:#8b949e'{GT}数值{LT}/th{GT}{LT}/tr{GT}"
    return f"{LT}table style='width:100%;border-collapse:collapse;font-size:0.85em'{GT}{hdr}{''.join(rows)}{LT}/table{GT}"


def _cn_details(details: str) -> str:
    """Translate English metric names in details string to Chinese."""
    trans = {
        "ROE": "ROE", "Net Margin": "净利率", "Op Margin": "营业利率",
        "Revenue Growth": "营收增速", "Earnings Growth": "盈利增速",
        "Current Ratio": "流动比率", "D/E": "D/E",
        "P/E": "P/E", "P/B": "P/B", "P/S": "P/S",
    }
    result = details
    for en, cn in trans.items():
        result = result.replace(en + ":", cn + ":")
    return result

def _fmt_fundamentals_reasoning(reasoning: dict) -> str:
    sections = [
        ("盈利能力", reasoning.get("profitability_signal", {}), ["ROE", "净利率", "营业利率"]),
        ("成长性", reasoning.get("growth_signal", {}), ["营收增速", "盈利增速"]),
        ("财务健康", reasoning.get("financial_health_signal", {}), ["流动比率", "D/E"]),
        ("估值比率", reasoning.get("price_ratios_signal", {}), ["P/E", "P/B", "P/S"]),
    ]
    rows = []
    for label, sec, fields in sections:
        sig = sec.get("signal", "neutral")
        details = sec.get("details", "")
        sc = {"bullish": "#3fb950", "bearish": "#f85149", "neutral": "#d2991d"}.get(sig, "#8b949e")
        rows.append(
            "<tr>"
            + "<td style='color:#58a6ff;font-weight:600'>" + label + "</td>"
            + "<td><span style='color:" + sc + ";font-weight:700'>" + _cn_sig(sig) + "</span></td>"
            + "<td style='font-size:0.8em;color:#8b949e'>" + _cn_details(details or "") + "</td>"
            + "</tr>"
        )
    if not rows:
        return json.dumps(reasoning, ensure_ascii=False, indent=2)
    hdr = (
        "<tr style='border-bottom:1px solid #21262d'>"
        + "<th style='text-align:left;padding:6px;color:#8b949e'>指标</th>"
        + "<th style='text-align:left;padding:6px;color:#8b949e'>信号</th>"
        + "<th style='text-align:left;padding:6px;color:#8b949e'>详情</th>"
        + "</tr>"
    )
    return "<table style='width:100%;border-collapse:collapse;font-size:0.85em'>" + hdr + "".join(rows) + "</table>"

def _fmt_growth_reasoning(reasoning: dict) -> str:
    cn_map = {
        "score": "得分", "signal": "信号", "confidence": "置信度",
        "revenue_growth": "营收增长", "revenue_trend": "营收趋势",
        "eps_growth": "EPS增长", "eps_trend": "EPS趋势",
        "fcf_growth": "FCF增长", "fcf_trend": "FCF趋势",
        "peg_ratio": "PEG", "price_to_sales_ratio": "P/S",
        "gross_margin": "毛利率", "gross_margin_trend": "毛利趋势",
        "operating_margin": "营业利率", "operating_margin_trend": "营业利趋势",
        "net_margin": "净利率", "net_margin_trend": "净利趋势",
        "net_flow_ratio": "内部人净流", "buys": "买入", "sells": "卖出",
        "debt_to_equity": "D/E", "current_ratio": "流动比率",
        "weighted_score": "综合得分",
    }
    sec_labels = {
        "historical_growth": ("历史增长", ["revenue_growth", "eps_growth", "fcf_growth", "revenue_trend", "eps_trend", "fcf_trend"]),
        "growth_valuation": ("增长估值", ["peg_ratio", "price_to_sales_ratio"]),
        "margin_expansion": ("利润率扩张", ["gross_margin", "operating_margin", "net_margin"]),
        "insider_conviction": ("内部人信心", ["net_flow_ratio", "buys", "sells"]),
        "financial_health": ("财务健康", ["debt_to_equity", "current_ratio"]),
        "final_analysis": ("最终", ["signal", "confidence", "weighted_score"]),
    }
    rows = []
    for sec_key, (sec_label, fields) in sec_labels.items():
        sec = reasoning.get(sec_key, {})
        if not sec:
            continue
        score = sec.get("score")
        sig = sec.get("signal", "")
        score_str = ""
        if score is not None:
            try:
                score_str = " score=" + "{:.2f}".format(float(score))
            except:
                pass
        vals = []
        for f in fields:
            v = sec.get(f)
            if v is not None:
                cn = cn_map.get(f, f)
                if isinstance(v, float):
                    vals.append(cn + ": " + ("{:.2f}".format(v) if abs(v) < 10 else "{:.1f}".format(v)))
                else:
                    vals.append(cn + ": " + str(v))
        vals_str = ", ".join(vals)
        sig_html = ""
        if sig:
            sc = {"bullish": "#3fb950", "bearish": "#f85149", "neutral": "#d2991d"}.get(str(sig).lower(), "#8b949e")
            sig_html = "<span style='color:" + sc + ";font-weight:700'>" + _cn_sig(sig) + "</span>"
        rows.append(
            "<tr>"
            + "<td style='color:#58a6ff;font-weight:600'>" + sec_label + score_str + "</td>"
            + "<td>" + sig_html + "</td>"
            + "<td style='font-size:0.8em;color:#8b949e'>" + vals_str + "</td>"
            + "</tr>"
        )
    if not rows:
        return json.dumps(reasoning, ensure_ascii=False, indent=2)
    hdr = (
        "<tr style='border-bottom:1px solid #21262d'>"
        + "<th style='text-align:left;padding:6px;color:#8b949e'>指标</th>"
        + "<th style='text-align:left;padding:6px;color:#8b949e'>信号</th>"
        + "<th style='text-align:left;padding:6px;color:#8b949e'>数值</th>"
        + "</tr>"
    )
    return "<table style='width:100%;border-collapse:collapse;font-size:0.85em'>" + hdr + "".join(rows) + "</table>"


def _fmt_sentiment_reasoning(reasoning: dict) -> str:
    insider = reasoning.get("insider_trading", {})
    news = reasoning.get("news_sentiment", {})
    combined = reasoning.get("combined_analysis", {})
    im = insider.get("metrics", {})
    nm = news.get("metrics", {})
    isig = _cn_sig(insider.get('signal', 'neutral'))
    nsig = _cn_sig(news.get('signal', 'neutral'))
    p = []
    p.append(f"{LT}div style='margin-bottom:10px'{GT}")
    p.append(f"{LT}div style='font-weight:600;color:#58a6ff;margin-bottom:4px'{GT}内幕交易分析{LT}/div{GT}")
    p.append(f"{LT}span style='font-size:0.85em;color:#8b949e'{GT}总交易: {im.get('total_trades',0)} | 看多: {im.get('bullish_trades',0)} | 看空: {im.get('bearish_trades',0)}{LT}/span{GT}")
    p.append(f"{LT}span class='signal-badge signal-{isig}' style='margin-left:8px'{GT}{isig} ({float(insider.get('confidence',0)):.0f}%){LT}/span{GT}{LT}/div{GT}")
    p.append(f"{LT}div style='margin-bottom:10px'{GT}")
    p.append(f"{LT}div style='font-weight:600;color:#58a6ff;margin-bottom:4px'{GT}新闻情绪分析{LT}/div{GT}")
    p.append(f"{LT}span style='font-size:0.85em;color:#8b949e'{GT}总文章: {nm.get('total_articles',0)} | 看多: {nm.get('bullish_articles',0)} | 看空: {nm.get('bearish_articles',0)}{LT}/span{GT}")
    p.append(f"{LT}span class='signal-badge signal-{nsig}' style='margin-left:8px'{GT}{nsig} ({float(news.get('confidence',0)):.0f}%){LT}/span{GT}{LT}/div{GT}")
    p.append(f"{LT}div style='padding:8px;background:#1c2128;border-radius:6px;font-size:0.85em;color:#d2991d'{GT}综合结论: {combined.get('signal_determination', 'N/A')}{LT}/div{GT}")
    return ''.join(p)


def _fmt_news_sentiment_reasoning(reasoning: dict) -> str:
    ns = reasoning.get("news_sentiment", {})
    m = ns.get("metrics", {})
    sig_cn = _cn_sig(ns.get('signal', 'neutral'))
    sig_en = ns.get('signal', 'neutral').upper()
    total = m.get('total_articles', 0)
    bull = m.get('bullish_articles', 0)
    bear = m.get('bearish_articles', 0)
    neut = m.get('neutral_articles', 0)
    bp = m.get('bullish_pct', round(bull/total*100,1) if total > 0 else 0)
    bep = m.get('bearish_pct', round(bear/total*100,1) if total > 0 else 0)
    np_val = m.get('neutral_pct', round(neut/total*100,1) if total > 0 else 0)
    classified = m.get('articles_classified_by_llm', 0)
    details = ns.get("article_details", [])
    p = []
    p.append("<div>")
    p.append("<div style='font-weight:600;color:#58a6ff;margin-bottom:4px'>新闻情绪分析 (DeepSeek)</div>")
    p.append(f"<div style='font-size:0.85em;color:#8b949e;margin-bottom:6px'>总文章: {total} | LLM分类: {classified}</div>")
    p.append("<div style='display:flex;gap:8px;margin-bottom:8px'>")
    for label, cnt, pct_val, clr in [("看多", bull, bp, "#3fb950"), ("看空", bear, bep, "#f85149"), ("中性", neut, np_val, "#d2991d")]:
        p.append(f"<div style='flex:1;text-align:center'>")
        p.append(f"<div style='font-size:0.75em;color:#8b949e'>{label}</div>")
        p.append(f"<div style='font-size:1.1em;font-weight:700;color:{clr}'>{cnt} ({pct_val}%)</div>")
        p.append(f"<div style='height:4px;background:#21262d;border-radius:2px;margin-top:2px'><div style='width:{pct_val}%;height:4px;background:{clr};border-radius:2px'></div></div>")
        p.append("</div>")
    p.append("</div>")
    p.append(f"<span class='signal-badge signal-{sig_en}'>{sig_cn} ({float(ns.get('confidence',0)):.0f}%)</span>")
    if details:
        p.append("<div style='margin-top:8px;max-height:160px;overflow-y:auto'>")
        for d in details[:10]:
            sc_art = {"positive": "#3fb950", "negative": "#f85149", "neutral": "#d2991d"}.get(d.get('sentiment',''), "#8b949e")
            title = (d.get('title', '') or '')[:60]
            conf_art = d.get('confidence', 0)
            sent_art = d.get('sentiment', 'neutral')
            p.append(f"<div style='font-size:0.75em;color:{sc_art};padding:2px 0;border-bottom:1px solid #21262d'>[{sent_art}] ({conf_art}%) {title}</div>")
        p.append("</div>")
    p.append("</div>")
    return ''.join(p)


def _format_reasoning(reasoning, agent_name: str = "") -> str:
    if not reasoning:
        return f"{LT}span style='color:#484f58'{GT}无数据{LT}/span{GT}"
    # Try to parse JSON string reasoning first
    if isinstance(reasoning, str):
        try:
            parsed = json.loads(reasoning)
            if isinstance(parsed, dict):
                reasoning = parsed
        except (json.JSONDecodeError, TypeError):
            pass
    if isinstance(reasoning, dict):
        if "trend_following" in reasoning:
            return _fmt_technical_reasoning(reasoning)
        if "insider_trading" in reasoning:
            return _fmt_sentiment_reasoning(reasoning)
        if "profitability_signal" in reasoning:
            return _fmt_fundamentals_reasoning(reasoning)
        if "historical_growth" in reasoning:
            return _fmt_growth_reasoning(reasoning)
        ns = reasoning.get("news_sentiment", {})
        if ns and "articles_classified_by_llm" in str(ns.get("metrics", {})):
            return _fmt_news_sentiment_reasoning(reasoning)
        try:
            return f"{LT}pre style='font-size:0.8em;color:#8b949e;max-height:200px;overflow-y:auto'{GT}{json.dumps(reasoning, indent=2, ensure_ascii=False)}{LT}/pre{GT}"
        except:
            return str(reasoning)
    text = str(reasoning)
    low = text.lower()
    # Only show "数据不足" for genuinely short/no-data responses, not for detailed analyses
    # that merely mention a specific data gap in context
    if len(text) < 100 and ("insufficient data" in low or "no data" in low or "missing" in low):
        return f"{LT}div style='color:#d2991d'{GT}数据不足,无法给出明确判断{LT}/div{GT}"
    return f"{LT}div style='white-space:pre-wrap;word-break:break-word'{GT}{text}{LT}/div{GT}"


def generate_html_report(
    result: dict,
    tickers: list[str],
    model_name: str = "",
    model_provider: str = "",
    start_date: str = "",
    end_date: str = "",
    selected_analysts: Optional[list[str]] = None,
    output_path: Optional[str] = None,
) -> str:
    """Generate a full HTML report and save to output_path.
    
    Returns the file path.
    """
    decisions = result.get("decisions", {})
    analyst_signals = result.get("analyst_signals", {})

    # Count signals
    bullish = bearish = neutral = 0
    for agent, signals in analyst_signals.items():
        if agent == "risk_management_agent":
            continue
        for ticker, sig in signals.items():
            s = sig.get("signal", "").lower()
            if s == "bullish":
                bullish += 1
            elif s == "bearish":
                bearish += 1
            else:
                neutral += 1

    # Build sections
    header_html = _build_header(tickers, model_name, model_provider, start_date, end_date)
    decision_cards = _build_decision_cards(decisions)
    portfolio_summary = _build_portfolio_summary(decisions, bullish, bearish, neutral)
    agent_table = _build_agent_table(analyst_signals)
    detail_cards = _build_agent_detail_cards(analyst_signals, decisions)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI 对冲基金分析报告 - {' & '.join(tickers)}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Microsoft YaHei', 'PingFang SC', 'Segoe UI', Roboto, sans-serif;
    background: #0a0e17;
    color: #c9d1d9;
    line-height: 1.6;
}}
.container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}

/* Header */
.header {{
    background: linear-gradient(135deg, #1a1f2e 0%, #0d1117 50%, #1a1f2e 100%);
    border-bottom: 1px solid #21262d;
    padding: 40px 0;
    text-align: center;
}}
.header h1 {{
    font-size: 2.4em;
    font-weight: 800;
    background: linear-gradient(90deg, #58a6ff, #3fb950, #d2991d);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}}
.header .subtitle {{
    color: #8b949e;
    font-size: 0.95em;
    margin-top: 8px;
}}
.header .meta {{
    display: flex;
    justify-content: center;
    gap: 24px;
    margin-top: 16px;
    flex-wrap: wrap;
}}
.header .meta span {{
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 20px;
    padding: 4px 16px;
    font-size: 0.85em;
    color: #8b949e;
}}

/* Decision Cards */
.decision-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 20px;
    margin: 30px 0;
}}
.decision-card {{
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 12px;
    padding: 24px;
    text-align: center;
}}
.decision-card .ticker {{
    font-size: 1.4em;
    font-weight: 700;
    color: #58a6ff;
    margin-bottom: 12px;
}}
.decision-card .action {{
    display: inline-block;
    font-size: 1.8em;
    font-weight: 800;
    padding: 8px 28px;
    border-radius: 8px;
    margin: 8px 0;
}}
.action-BUY, .action-COVER {{ background: #0d3320; color: #3fb950; border: 2px solid #238636; }}
.action-SELL, .action-SHORT {{ background: #331212; color: #f85149; border: 2px solid #da3633; }}
.action-HOLD {{ background: #1d2214; color: #d2991d; border: 2px solid #9e6a03; }}
.decision-card .confidence {{
    font-size: 0.9em;
    color: #8b949e;
    margin-top: 8px;
}}
.decision-card .confidence-bar {{
    width: 100%;
    height: 6px;
    background: #21262d;
    border-radius: 3px;
    margin-top: 8px;
    overflow: hidden;
}}
.decision-card .confidence-fill {{
    height: 100%;
    border-radius: 3px;
    transition: width 0.5s ease;
}}

/* 投资组合摘要 */
.portfolio-summary {{
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 12px;
    padding: 24px;
    margin: 20px 0;
}}
.portfolio-summary h2 {{
    color: #58a6ff;
    font-size: 1.2em;
    margin-bottom: 16px;
}}
.signal-bars {{
    display: flex;
    gap: 12px;
    margin-bottom: 16px;
}}
.signal-bar {{
    flex: 1;
    text-align: center;
}}
.signal-bar .label {{
    font-size: 0.8em;
    color: #8b949e;
    margin-bottom: 4px;
}}
.signal-bar .bar {{
    height: 8px;
    border-radius: 4px;
    margin-bottom: 4px;
}}
.signal-bar .count {{
    font-size: 1.5em;
    font-weight: 700;
}}
.bullish-bar {{ background: #238636; }}
.bearish-bar {{ background: #da3633; }}
.neutral-bar {{ background: #9e6a03; }}
.bullish-text {{ color: #3fb950; }}
.bearish-text {{ color: #f85149; }}
.neutral-text {{ color: #d2991d; }}

/* Tables */
.agent-table {{
    width: 100%;
    border-collapse: collapse;
    margin: 20px 0;
    font-size: 0.9em;
}}
.agent-table th {{
    background: #21262d;
    color: #8b949e;
    font-weight: 600;
    text-align: left;
    padding: 12px 16px;
    border-bottom: 2px solid #30363d;
    position: sticky;
    top: 0;
}}
.agent-table td {{
    padding: 12px 16px;
    border-bottom: 1px solid #21262d;
}}
.agent-table tr:hover {{ background: #1c2128; }}

/* 代理 Detail Cards */
.agent-detail-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
    gap: 16px;
    margin: 20px 0;
}}
.agent-card {{
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
    overflow: hidden;
}}
.agent-card-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 18px;
    border-bottom: 1px solid #21262d;
}}
.agent-card-header .name {{
    font-weight: 600;
    font-size: 0.95em;
}}
.agent-card-header .signal-badge {{
    padding: 3px 12px;
    border-radius: 12px;
    font-size: 0.8em;
    font-weight: 700;
}}
.signal-BULLISH {{ background: #0d3320; color: #3fb950; }}
.signal-BEARISH {{ background: #331212; color: #f85149; }}
.signal-NEUTRAL {{ background: #1d2214; color: #d2991d; }}
.agent-card-body {{
    padding: 14px 18px;
    font-size: 0.85em;
    color: #8b949e;
    max-height: 300px;
    overflow-y: auto;
}}
.agent-card-body .reasoning {{
    white-space: pre-wrap;
    word-break: break-word;
}}
.agent-card-footer {{
    padding: 10px 18px;
    border-top: 1px solid #21262d;
    font-size: 0.8em;
    color: #484f58;
}}

/* Footer */
.footer {{
    text-align: center;
    padding: 30px;
    color: #484f58;
    font-size: 0.8em;
    border-top: 1px solid #21262d;
    margin-top: 40px;
}}

/* Print */
@media print {{
    body {{ background: white; color: black; }}
    .header {{ background: #f0f0f0; }}
    .agent-card, .decision-card, .portfolio-summary {{
        background: white;
        border: 1px solid #ccc;
    }}
}}

/* Scrollbar */
::-webkit-scrollbar {{ width: 8px; }}
::-webkit-scrollbar-track {{ background: #0d1117; }}
::-webkit-scrollbar-thumb {{ background: #30363d; border-radius: 4px; }}
</style>
</head>
<body>
{header_html}
<div class="container">
{decision_cards}
{portfolio_summary}
{agent_table}
{detail_cards}
</div>
<div class="footer">
    AI 对冲基金 CN &middot; 生成时间 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} CST
</div>
</body>
</html>"""

    if output_path is None:
        results_dir = os.path.join(os.path.dirname(__file__), "..", "..", "results")
        os.makedirs(results_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(results_dir, f"report_{'_'.join(tickers)}_{ts}.html")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path


def _build_header(tickers, model_name, model_provider, start_date, end_date):
    ticker_str = " & ".join(tickers)
    return f"""<div class="header">
<h1>AI 对冲基金 · A股分析报告</h1>
<div class="subtitle">多代理联合投研报告</div>
<div class="meta">
<span>&#x1f4c8; {ticker_str}</span>
<span>&#x1f9e0; {model_provider} / {model_name}</span>
<span>&#x1f4c5; {start_date} &rarr; {end_date}</span>
</div>
</div>"""


def _build_decision_cards(decisions):
    if not decisions:
        return '<div class="decision-grid"><p>无交易决策。</p></div>'
    cards = []
    for ticker, d in decisions.items():
        action = d.get("action", "HOLD").upper()
        action_cn = _cn_action(action)
        confidence = d.get("confidence", 0)
        reasoning = d.get("reasoning", "")
        confidence_pct = min(float(confidence), 100) if confidence else 0
        bar_color = "#3fb950" if action in ("BUY", "COVER") else "#f85149" if action in ("SELL", "SHORT") else "#d2991d"
        cards.append(f"""<div class="decision-card">
<div class="ticker">{ticker}</div>
<div class="action action-{action}">{action_cn}</div>
<div class="confidence">信心度: <strong>{confidence_pct:.1f}%</strong></div>
<div class="confidence-bar"><div class="confidence-fill" style="width:{confidence_pct}%;background:{bar_color};"></div></div>
<div style="margin-top:12px;font-size:0.85em;color:#8b949e;">{reasoning[:200]}{"..." if len(reasoning) > 200 else ""}</div>
</div>""")
    return '<div class="decision-grid">' + "".join(cards) + '</div>'


def _build_portfolio_summary(decisions, bullish, bearish, neutral):
    total = bullish + bearish + neutral
    if total == 0:
        return ""
    bp = bullish / total * 100
    bep = bearish / total * 100
    np = neutral / total * 100

    rows = []
    for ticker, d in decisions.items():
        action = d.get("action", "").upper()
        action_cn = _cn_action(action)
        qty = d.get("quantity", 0)
        conf = d.get("confidence", 0)
        ac = "action-{action}".format(action=action)
        rows.append(f"""<tr>
<td style="color:#58a6ff;font-weight:600;">{ticker}</td>
<td><span class="action {ac}">{action_cn}</span></td>
<td>{qty}</td>
<td>{float(conf):.1f}%</td>
</tr>""")

    return f"""<div class="portfolio-summary">
<h2>&#x1f4ca; 投资组合摘要</h2>
<div class="signal-bars">
<div class="signal-bar">
<div class="label">看多</div>
<div class="bar bullish-bar" style="width:100%;opacity:0.3;"></div>
<div class="count bullish-text">{bullish}</div>
</div>
<div class="signal-bar">
<div class="label">看空</div>
<div class="bar bearish-bar" style="width:100%;opacity:0.3;"></div>
<div class="count bearish-text">{bearish}</div>
</div>
<div class="signal-bar">
<div class="label">中性</div>
<div class="bar neutral-bar" style="width:100%;opacity:0.3;"></div>
<div class="count neutral-text">{neutral}</div>
</div>
</div>
<table class="agent-table">
<thead><tr><th>代码</th><th>操作</th><th>数量</th><th>信心</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>
</div>"""


def _build_agent_table(analyst_signals):
    """Compact overview table."""
    rows = []
    agent_name_map = {
        "Fundamentals Analyst": "基本面分析师",
        "Technical Analyst": "技术分析师",
        "Sentiment Analyst": "市场情绪分析师",
        "News Sentiment": "新闻情绪分析师",
        "Growth Analyst": "成长分析师",
        "Valuation Analyst": "估值分析师",
        "Risk Management": "风险管理师",
        "Portfolio Manager": "投资组合管理师",
    }
    for agent, signals in analyst_signals.items():
        if agent == "risk_management_agent":
            continue
        agent_display_en = agent.replace("_agent", "").replace("_", " ").title()
        agent_display = agent_name_map.get(agent_display_en, agent_display_en)
        for ticker, sig in signals.items():
            signal = sig.get("signal", "NEUTRAL").upper()
            signal_cn = _cn_sig(signal)
            confidence = sig.get("confidence", 0)
            reasoning_raw = sig.get("reasoning", "")
            reasoning_short = _format_reasoning(reasoning_raw, agent)
            # Strip HTML tags for the short preview in the table
            import re as _re
            text_only = _re.sub(r'<[^>]+>', '', str(reasoning_short))
            reasoning_short = text_only[:100] + ("..." if len(text_only) > 100 else "")
            sc = f"signal-{signal}"
            rows.append(f"""<tr>
<td style="color:#58a6ff;">{agent_display}</td>
<td style="color:#c9d1d9;">{ticker}</td>
<td><span class="signal-badge {sc}">{signal_cn}</span></td>
<td>{float(confidence):.1f}%</td>
<td style="color:#8b949e;font-size:0.85em;">{reasoning_short}</td>
</tr>""")

    if not rows:
        return ""

    return f"""<div style="margin:30px 0;">
<h2 style="color:#58a6ff;margin-bottom:12px;">&#x1f9e0; 代理分析概览</h2>
<table class="agent-table">
<thead><tr><th>代理</th><th>代码</th><th>信号</th><th>置信</th><th style="min-width:300px;">分析内容</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>
</div>"""


def _build_agent_detail_cards(analyst_signals, decisions):
    """Individual detail cards for each agent."""
    cards = []
    agent_name_map = {
        "Fundamentals Analyst": "基本面分析师",
        "Technical Analyst": "技术分析师",
        "Sentiment Analyst": "市场情绪分析师",
        "News Sentiment": "新闻情绪分析师",
        "Growth Analyst": "成长分析师",
        "Valuation Analyst": "估值分析师",
        "Risk Management": "风险管理师",
        "Portfolio Manager": "投资组合管理师",
    }
    for agent, signals in analyst_signals.items():
        if agent == "risk_management_agent":
            continue
        agent_display_en = agent.replace("_agent", "").replace("_", " ").title()
        agent_display = agent_name_map.get(agent_display_en, agent_display_en)
        for ticker, sig in signals.items():
            signal = sig.get("signal", "NEUTRAL").upper()
            signal_cn = _cn_sig(signal)
            confidence = sig.get("confidence", 0)
            reasoning = sig.get("reasoning", "")
            formatted_rd = _format_reasoning(reasoning, agent)
            sc = f"signal-{signal}"
            cards.append(f"""<div class="agent-card">
<div class="agent-card-header">
<span class="name">&#x1f9e0; {agent_display} &rarr; <span style="color:#58a6ff;">{ticker}</span></span>
<span class="signal-badge {sc}">{signal_cn} {float(confidence):.0f}%</span>
</div>
<div class="agent-card-body">
{formatted_rd}
</div>
<div class="agent-card-footer">代理: {agent_display} &middot; 信心度: {float(confidence):.1f}%</div>
</div>""")

    if not cards:
        return ""

    return f"""<div style="margin:30px 0;">
<h2 style="color:#58a6ff;margin-bottom:12px;">&#x1f50d; 代理详细分析</h2>
<div class="agent-detail-grid">
{"".join(cards)}
</div>
</div>"""