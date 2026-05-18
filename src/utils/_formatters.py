import json

LT = chr(60)
GT = chr(62)

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
                    vals += f"{LT}div style='font-size:0.8em;color:#8b949e;'{GT}{cn}: {LT}b{GT}{v}{LT}/b{GT}{LT}/div{GT}"
            rows.append(f"{LT}tr{GT}{LT}td style='color:#58a6ff;font-weight:600'{GT}{label}{LT}/td{GT}{LT}td{GT}{LT}span style='color:{sc};font-weight:700'{GT}{sig.upper()}{LT}/span{GT}{LT}/td{GT}{LT}td{GT}{float(conf):.0f}%{LT}/td{GT}{LT}td{GT}{vals}{LT}/td{GT}{LT}/tr{GT}")
    if not rows:
        return json.dumps(reasoning, ensure_ascii=False, indent=2)
    hdr = f"{LT}tr style='border-bottom:1px solid #21262d'{GT}{LT}th style='text-align:left;padding:6px;color:#8b949e'{GT}指标{LT}/th{GT}{LT}th style='text-align:left;padding:6px;color:#8b949e'{GT}信号{LT}/th{GT}{LT}th style='text-align:left;padding:6px;color:#8b949e'{GT}置信{LT}/th{GT}{LT}th style='text-align:left;padding:6px;color:#8b949e'{GT}数值{LT}/th{GT}{LT}/tr{GT}"
    return f"{LT}table style='width:100%;border-collapse:collapse;font-size:0.85em'{GT}{hdr}{''.join(rows)}{LT}/table{GT}"
def _fmt_sentiment_reasoning(reasoning: dict) -> str:
    insider = reasoning.get("insider_trading", {})
    news = reasoning.get("news_sentiment", {})
    combined = reasoning.get("combined_analysis", {})
    im = insider.get("metrics", {})
    nm = news.get("metrics", {})
    isig = insider.get('signal', 'neutral').upper()
    nsig = news.get('signal', 'neutral').upper()
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
    sig = ns.get('signal', 'neutral').upper()
    p = []
    p.append(f"{LT}div{GT}")
    p.append(f"{LT}div style='font-weight:600;color:#58a6ff;margin-bottom:4px'{GT}新闻情绪分析{LT}/div{GT}")
    p.append(f"{LT}span style='font-size:0.85em;color:#8b949e'{GT}总文章: {m.get('total_articles',0)} | 看多: {m.get('bullish_articles',0)} | 看空: {m.get('bearish_articles',0)} | LLM分类: {m.get('articles_classified_by_llm',0)}{LT}/span{GT}")
    p.append(f"{LT}span class='signal-badge signal-{sig}' style='margin-left:8px'{GT}{sig} ({float(ns.get('confidence',0)):.0f}%){LT}/span{GT}{LT}/div{GT}")
    return ''.join(p)


def _format_reasoning(reasoning, agent_name: str = "") -> str:
    if not reasoning:
        return f"{LT}span style='color:#484f58'{GT}无数据{LT}/span{GT}"
    if isinstance(reasoning, dict):
        if "trend_following" in reasoning:
            return _fmt_technical_reasoning(reasoning)
        if "insider_trading" in reasoning:
            return _fmt_sentiment_reasoning(reasoning)
        ns = reasoning.get("news_sentiment", {})
        if ns and "articles_classified_by_llm" in str(ns.get("metrics", {})):
            return _fmt_news_sentiment_reasoning(reasoning)
        try:
            return f"{LT}pre style='font-size:0.8em;color:#8b949e;max-height:200px;overflow-y:auto'{GT}{json.dumps(reasoning, indent=2, ensure_ascii=False)}{LT}/pre{GT}"
        except:
            return str(reasoning)
    text = str(reasoning)
    low = text.lower()
    if len(text) < 100 and ("insufficient data" in low or "no data" in low or "missing" in low):
        return f"{LT}div style='color:#d2991d'{GT}数据不足,无法给出明确判断{LT}/div{GT}"
    return f"{LT}div style='white-space:pre-wrap;word-break:break-word'{GT}{text}{LT}/div{GT}"
