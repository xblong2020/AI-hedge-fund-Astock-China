import sys

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph
from colorama import Fore, Style, init
import questionary
from src.agents.portfolio_manager import portfolio_management_agent
from src.agents.risk_manager import risk_management_agent
from src.graph.state import AgentState
from src.utils.display import print_trading_output
from src.utils.analysts import ANALYST_ORDER, get_analyst_nodes
from src.utils.progress import progress
from src.utils.visualize import save_graph_as_png
from src.utils.html_report import generate_html_report
from src.cli.input import (
    parse_cli_inputs,
)

import argparse
from datetime import datetime
from dateutil.relativedelta import relativedelta
import json
import sys
# Fix GBK console encoding: replace chars that can't be encoded
if sys.stdout.encoding and sys.stdout.encoding.lower() in ("gbk", "cp936"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


# Load environment variables from .env file
load_dotenv()

init(autoreset=True)


def parse_hedge_fund_response(response):
    """Parses a JSON string and returns a dictionary."""
    try:
        return json.loads(response)
    except json.JSONDecodeError as e:
        print(f"JSON decoding error: {e}\nResponse: {repr(response)}")
        return None
    except TypeError as e:
        print(f"Invalid response type (expected string, got {type(response).__name__}): {e}")
        return None
    except Exception as e:
        print(f"Unexpected error while parsing response: {e}\nResponse: {repr(response)}")
        return None


##### Run the Hedge Fund #####
def run_hedge_fund(
    tickers: list[str],
    start_date: str,
    end_date: str,
    portfolio: dict,
    show_reasoning: bool = False,
    selected_analysts: list[str] = [],
    model_name: str = "gpt-4.1",
    model_provider: str = "OpenAI",
):
    # Start progress tracking
    progress.start()

    try:
        # Pre-fetch CN A-share data from Tushare (download data once, agents read from cache)
        from src.tools.cn_data import _is_cn_ticker, prefetch_cn_data
        for ticker in tickers:
            if _is_cn_ticker(ticker):
                print(f"  [..] Pre-fetching Tushare data for {ticker}...")
                prefetch_cn_data(ticker, end_date, start_date)
                print(f"  [OK] Tushare data ready for {ticker}")

        # Build workflow (default to all analysts when none provided)
        workflow = create_workflow(selected_analysts if selected_analysts else None)
        agent = workflow.compile()

        final_state = agent.invoke(
            {
                "messages": [
                    HumanMessage(
                        content="Make trading decisions based on the provided data.",
                    )
                ],
                "data": {
                    "tickers": tickers,
                    "portfolio": portfolio,
                    "start_date": start_date,
                    "end_date": end_date,
                    "analyst_signals": {},
                },
                "metadata": {
                    "show_reasoning": show_reasoning,
                    "model_name": model_name,
                    "model_provider": model_provider,
                },
            },
        )

        return {
            "decisions": parse_hedge_fund_response(final_state["messages"][-1].content),
            "analyst_signals": final_state["data"]["analyst_signals"],
        }
    finally:
        # Stop progress tracking
        progress.stop()


def start(state: AgentState):
    """Initialize the workflow with the input message."""
    return state


def create_workflow(selected_analysts=None):
    """Create the workflow with selected analysts."""
    workflow = StateGraph(AgentState)
    workflow.add_node("start_node", start)

    # Get analyst nodes from the configuration
    analyst_nodes = get_analyst_nodes()

    # Default to all analysts if none selected
    if selected_analysts is None:
        selected_analysts = list(analyst_nodes.keys())
    # Add selected analyst nodes
    for analyst_key in selected_analysts:
        node_name, node_func = analyst_nodes[analyst_key]
        workflow.add_node(node_name, node_func)
        workflow.add_edge("start_node", node_name)

    # Always add risk and portfolio management
    workflow.add_node("risk_management_agent", risk_management_agent)
    workflow.add_node("portfolio_manager", portfolio_management_agent)

    # Connect selected analysts to risk management
    for analyst_key in selected_analysts:
        node_name = analyst_nodes[analyst_key][0]
        workflow.add_edge(node_name, "risk_management_agent")

    workflow.add_edge("risk_management_agent", "portfolio_manager")
    workflow.add_edge("portfolio_manager", END)

    workflow.set_entry_point("start_node")
    return workflow


if __name__ == "__main__":
    inputs = parse_cli_inputs(
        description="Run the hedge fund trading system",
        require_tickers=True,
        include_html_flag=True,
        default_months_back=None,
        include_graph_flag=True,
        include_reasoning_flag=True,
    )

    tickers = inputs.tickers
    selected_analysts = inputs.selected_analysts

    # Construct portfolio here
    portfolio = {
        "cash": inputs.initial_cash,
        "margin_requirement": inputs.margin_requirement,
        "margin_used": 0.0,
        "positions": {
            ticker: {
                "long": 0,
                "short": 0,
                "long_cost_basis": 0.0,
                "short_cost_basis": 0.0,
                "short_margin_used": 0.0,
            }
            for ticker in tickers
        },
        "realized_gains": {
            ticker: {
                "long": 0.0,
                "short": 0.0,
            }
            for ticker in tickers
        },
    }

    result = run_hedge_fund(
        tickers=tickers,
        start_date=inputs.start_date,
        end_date=inputs.end_date,
        portfolio=portfolio,
        show_reasoning=inputs.show_reasoning,
        selected_analysts=inputs.selected_analysts,
        model_name=inputs.model_name,
        model_provider=inputs.model_provider,
    )

    # Save results to JSON + HTML FIRST (before console output which may crash)
    # Save results to JSON file
    import os
    from datetime import datetime
    results_dir = os.path.join(os.path.dirname(__file__), "..", "results")
    os.makedirs(results_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_file = os.path.join(results_dir, f"hedgefund_{'_'.join(tickers)}_{timestamp}.json")
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n[Result saved to: {result_file}]")

    # Generate HTML report if requested
    if inputs.show_html:
        html_path = generate_html_report(
            result,
            tickers=tickers,
            model_name=inputs.model_name,
            model_provider=inputs.model_provider,
            start_date=inputs.start_date,
            end_date=inputs.end_date,
            selected_analysts=inputs.selected_analysts,
        )
        print(f"[HTML Report saved to: {html_path}]")

    # Print to console (wrapped to survive encoding errors)
    try:
        print_trading_output(result)
    except Exception as e:
        print(f"(Console output skipped: {e})")
