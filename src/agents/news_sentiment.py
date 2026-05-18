

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from src.data.models import CompanyNews
import pandas as pd
import numpy as np
import json

from src.graph.state import AgentState, show_agent_reasoning
from src.tools.api import get_company_news
from src.utils.api_key import get_api_key_from_state
from src.utils.llm import call_llm
from src.utils.progress import progress
from typing_extensions import Literal


class ArticleSentiment(BaseModel):
    index: int
    sentiment: Literal["positive", "negative", "neutral"]
    confidence: int = Field(description="Confidence 0-100")

class BatchSentiment(BaseModel):
    articles: list[ArticleSentiment]

class Sentiment(BaseModel):
    """Represents the sentiment of a news article."""

    sentiment: Literal["positive", "negative", "neutral"]
    confidence: int = Field(description="Confidence 0-100")


def news_sentiment_agent(state: AgentState, agent_id: str = "news_sentiment_agent"):
    """
    Analyzes news sentiment for a list of tickers and generates trading signals.

    This agent fetches company news, uses an LLM to classify the sentiment of articles
    with missing sentiment data, and then aggregates the sentiments to produce an
    overall signal (bullish, bearish, or neutral) and a confidence score for each ticker.

    Args:
        state: The current state of the agent graph.
        agent_id: The ID of the agent.

    Returns:
        A dictionary containing the updated state with the agent's analysis.
    """
    data = state.get("data", {})
    end_date = data.get("end_date")
    tickers = data.get("tickers")
    api_key = get_api_key_from_state(state, "FINANCIAL_DATASETS_API_KEY")
    sentiment_analysis = {}

    for ticker in tickers:
        progress.update_status(agent_id, ticker, "Fetching company news")
        company_news = get_company_news(
            ticker=ticker,
            end_date=end_date,
            limit=100,
            api_key=api_key,
        )

        company_news = company_news or []
        news_signals = []
        sentiment_confidences = {}
        sentiments_classified_by_llm = 0
        article_details = []  # Store per-article results
        
        if company_news:
            # Take up to 30 most recent articles for LLM classification
            articles_to_analyze = company_news[:30]
            
            if articles_to_analyze:
                progress.update_status(agent_id, ticker, f"Analyzing sentiment for {len(articles_to_analyze)} articles (batched)")
                
                # Batch classify: send up to 10 titles per LLM call
                batch_size = 10
                for batch_start in range(0, len(articles_to_analyze), batch_size):
                    batch = articles_to_analyze[batch_start:batch_start + batch_size]
                    batch_end = min(batch_start + len(batch), len(articles_to_analyze))
                    progress.update_status(agent_id, ticker, f"Classifying articles {batch_start+1}-{batch_end} of {len(articles_to_analyze)}")
                    
                    titles = []
                    for i, news in enumerate(batch):
                        titles.append(f"[{i+1}] {news.title}")
                    titles_text = "\n".join(titles)
                    
                    prompt = (
                        f"Analyze the sentiment of the following news headlines for stock {ticker}. "
                        f"For EACH article, determine if sentiment is 'positive', 'negative', or 'neutral' for {ticker}. "
                        f"Also provide a confidence score 0-100 for each. "
                        f"Respond in JSON format with an array of objects: "
                        f'[{{"index": 1, "sentiment": "positive", "confidence": 85}}, ...]\n\n'
                        f"{titles_text}"
                    )
                    
                    try:
                        response = call_llm(prompt, BatchSentiment, agent_name=agent_id, state=state)
                        if response and response.articles:
                            for art in response.articles:
                                idx = art.index - 1
                                if 0 <= idx < len(batch):
                                    batch[idx].sentiment = art.sentiment.lower()
                                    sentiment_confidences[id(batch[idx])] = art.confidence
                                    sentiments_classified_by_llm += 1
                                    article_details.append({
                                        "title": batch[idx].title[:80],
                                        "sentiment": art.sentiment.lower(),
                                        "confidence": art.confidence,
                                    })
                    except Exception as e:
                        # Fallback: mark batch as neutral on error
                        for news in batch:
                            if news.sentiment is None:
                                news.sentiment = "neutral"
                                sentiment_confidences[id(news)] = 0
                                article_details.append({
                                    "title": news.title[:80],
                                    "sentiment": "neutral",
                                    "confidence": 0,
                                })

            # Aggregate sentiment across all articles
            sentiment = pd.Series([n.sentiment for n in company_news]).dropna()
            news_signals = np.where(sentiment == "negative","bearish", np.where(sentiment == "positive", "bullish", "neutral")).tolist()

        progress.update_status(agent_id, ticker, "Aggregating signals")

        # Calculate the sentiment signals with percentages
        bullish_signals = news_signals.count("bullish")
        bearish_signals = news_signals.count("bearish")
        neutral_signals = news_signals.count("neutral")
        total_signals = len(news_signals)
        
        bullish_pct = round(bullish_signals / total_signals * 100, 1) if total_signals > 0 else 0
        bearish_pct = round(bearish_signals / total_signals * 100, 1) if total_signals > 0 else 0
        neutral_pct = round(neutral_signals / total_signals * 100, 1) if total_signals > 0 else 0

        if bullish_signals > bearish_signals:
            overall_signal = "bullish"
        elif bearish_signals > bullish_signals:
            overall_signal = "bearish"
        else:
            overall_signal = "neutral"

        confidence = _calculate_confidence_score(
            sentiment_confidences=sentiment_confidences,
            company_news=company_news,
            overall_signal=overall_signal,
            bullish_signals=bullish_signals,
            bearish_signals=bearish_signals,
            total_signals=total_signals
        )

        # Create reasoning for the news sentiment
        reasoning = {
            "news_sentiment": {
                "signal": overall_signal,
                "confidence": confidence,
                "metrics": {
                    "total_articles": total_signals,
                    "bullish_articles": bullish_signals,
                    "bearish_articles": bearish_signals,
                    "neutral_articles": neutral_signals,
                    "bullish_pct": bullish_pct,
                    "bearish_pct": bearish_pct,
                    "neutral_pct": neutral_pct,
                    "articles_classified_by_llm": sentiments_classified_by_llm,
                },
                "article_details": article_details[:20],  # Top 20 details
            }
        }

        # Create the sentiment analysis
        sentiment_analysis[ticker] = {
            "signal": overall_signal,
            "confidence": confidence,
            "reasoning": reasoning,
        }

        progress.update_status(agent_id, ticker, "Done", analysis=json.dumps(reasoning, indent=4))

    message = HumanMessage(
        content=json.dumps(sentiment_analysis),
        name=agent_id,
    )

    if state.get("metadata", {}).get("show_reasoning"):
        show_agent_reasoning(sentiment_analysis, "News Sentiment Analysis Agent")

    if "analyst_signals" not in state["data"]:
        state["data"]["analyst_signals"] = {}
    state["data"]["analyst_signals"][agent_id] = sentiment_analysis

    progress.update_status(agent_id, None, "Done")

    return {
        "messages": [message],
        "data": state["data"],
    }


def _calculate_confidence_score(
    sentiment_confidences: dict,
    company_news: list,
    overall_signal: str,
    bullish_signals: int,
    bearish_signals: int,
    total_signals: int
) -> float:
    """
    Calculate confidence score for a sentiment signal.
    
    Uses a weighted approach combining LLM confidence scores (70%) with 
    signal proportion (30%) when LLM classifications are available.
    
    Args:
        sentiment_confidences: Dictionary mapping news article IDs to confidence scores.
        company_news: List of CompanyNews objects.
        overall_signal: The overall sentiment signal ("bullish", "bearish", or "neutral").
        bullish_signals: Count of bullish signals.
        bearish_signals: Count of bearish signals.
        total_signals: Total number of signals.
        
    Returns:
        Confidence score as a float between 0 and 100.
    """
    if total_signals == 0:
        return 0.0
    
    # Calculate weighted confidence using LLM confidence scores when available
    if sentiment_confidences:
        # Get articles that match the overall signal
        matching_articles = [
            news for news in company_news 
            if news.sentiment and (
                (overall_signal == "bullish" and news.sentiment == "positive") or
                (overall_signal == "bearish" and news.sentiment == "negative") or
                (overall_signal == "neutral" and news.sentiment == "neutral")
            )
        ]
        
        # Calculate average confidence from LLM-classified articles that match the signal
        llm_confidences = [
            sentiment_confidences[id(news)] 
            for news in matching_articles 
            if id(news) in sentiment_confidences
        ]
        
        if llm_confidences:
            # Weight: 70% from LLM confidence scores, 30% from signal proportion
            avg_llm_confidence = sum(llm_confidences) / len(llm_confidences)
            signal_proportion = (max(bullish_signals, bearish_signals) / total_signals) * 100
            return round(0.7 * avg_llm_confidence + 0.3 * signal_proportion, 2)
    
    # Fallback to proportion-based confidence
    return round((max(bullish_signals, bearish_signals) / total_signals) * 100, 2)
