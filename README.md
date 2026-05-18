# AI 对冲基金 — A股多代理分析系统

> 基于 AI 的多代理 A 股投资决策系统，使用 19 个专业代理（分析师）联合研判，生成交易信号与 HTML 分析报告。
>
> **⚠️ 免责声明：本项目仅供学习和研究使用，不构成任何投资建议。**

---

## 项目概述

本项目是 [ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) 的 A 股中文适配版，针对中国 A 股市场做了以下增强：

- **A 股数据源**：集成 Tushare + Eastmoney + AKShare，覆盖行情、财务、估值、资金流向、新闻、内部人交易等
- **中文化**：HTML 报告全中文化，代理分析输出中文
- **DeepSeek 优先**：默认使用 DeepSeek 模型，同时支持 OpenAI、Anthropic、Groq 等多种 LLM
- **新增代理**：Nassim Taleb（黑天鹅分析）、News Sentiment（新闻情绪）、Growth Analyst（增长分析）
- **本地计算**：P/S、PEG、FCF 增长率等指标基于 Tushare 数据本地计算，无需外部 API

## 代理体系（21 个代理）

### 投资大师代理（13 位）
| 代理 | 风格 | 说明 |
|------|------|------|
| Warren Buffett | 价值投资 | 寻找具有护城河的优质公司，以合理价格买入 |
| Charlie Munger | 理性投资 | 只买优质企业，强调能力圈和长期持有 |
| Ben Graham | 价值投资之父 | 强调安全边际，寻找被低估的基本面优良公司 |
| Peter Lynch | 十倍股猎手 | "买你所知"，寻找日常生活中的成长股 |
| Phil Fisher | 闲聊法投资 | 深度调研管理层和产品创新，追求长期成长 |
| Bill Ackman | 激进投资者 | 通过积极主义推动管理层释放价值 |
| Cathie Wood | 成长投资女王 | 聚焦颠覆性创新和技术变革 |
| Michael Burry | 逆向投资者 | 做空高估市场，深度基本面分析 |
| Mohnish Pabrai | Dhandho 投资者 | 低风险博取翻倍收益 |
| Nassim Taleb | 黑天鹅分析师 | 关注尾部风险、反脆弱性和非对称收益 |
| Rakesh Jhunjhunwala | 印度巴菲特 | 宏观经济驱动的成长行业投资 |
| Stanley Druckenmiller | 宏观投资大师 | 寻找具有增长潜力的非对称机会 |
| Aswath Damodaran | 估值教父 | 故事+数字，纪律性估值 |

### 专业分析代理（6 个）
| 代理 | 功能 |
|------|------|
| Fundamentals Analyst | 基本面分析：盈利能力、成长性、财务健康、估值比率 |
| Technical Analyst | 技术分析：动量、波动率、偏度/峰度、成交量 |
| Valuation Analyst | 估值分析：DCF 估值、DDM 估值、可比估值 |
| Sentiment Analyst | 市场情绪分析：社交媒体、新闻情绪、投资者行为 |
| News Sentiment | 新闻情绪：批量 DeepSeek 分类（看多/看空/中性 + 百分比）|
| Growth Analyst | 增长分析：历史增长、PEG、利润率扩张、FCF 趋势 |

### 决策代理（2 个）
| 代理 | 功能 |
|------|------|
| Risk Manager | 风险管理：计算风险指标、设定仓位限制 |
| Portfolio Manager | 投资组合管理：汇总信号、做出最终交易决策 |

## 数据源

| 数据 | 来源 | 说明 |
|------|------|------|
| 行情（日线/分钟） | Tushare / AKShare | K 线、成交量、换手率等 |
| 财务报表 | Tushare / Eastmoney | 利润表、资产负债表、现金流量表 |
| 财务指标 | Tushare `fina_indicator` | ROE、ROA、毛利率、净利率、fcff 等 |
| 估值数据 | 本地计算 | P/S、PEG、FCF 增长率基于 Tushare 数据计算 |
| 新闻 | Eastmoney / AKShare | 东财新闻、财联社 |
| 内部人交易 | Eastmoney / Tavily | 管理层持股变动 |
| 技术指标 | 本地计算 | 动量、偏度、峰度、波动率、RSI、MACD 等 |

## 环境要求

- **Python**: 3.11+
- **Tushare Pro Token**: 从 [tushare.pro](https://tushare.pro) 注册获取（需积分 >= 2000 以使用 `fina_indicator` 接口）
- **LLM API Key**: 至少一个（推荐 DeepSeek）

## 快速开始

### 1. 克隆并安装依赖

```powershell
# 克隆项目
git clone <your-repo-url> ai-hedge-fund-cn
cd ai-hedge-fund-cn

# 创建虚拟环境（推荐 Python 3.11）
python -m venv .venv
.venv\Scripts\activate

# 安装 Poetry
pip install poetry

# 安装项目依赖
poetry install
```

### 2. 配置环境变量

```powershell
copy .env.example .env
```

编辑 `.env` 文件，填入以下必要配置：

```env
# Tushare Pro Token（必填 — A 股数据来源）
TUSHARE_TOKEN=your-tushare-token

# DeepSeek API Key（推荐）
DEEPSEEK_API_KEY=sk-your-deepseek-api-key

# 或使用 OpenAI
# OPENAI_API_KEY=sk-your-openai-api-key

# 或使用其他 LLM
# ANTHROPIC_API_KEY=your-anthropic-api-key
# GROQ_API_KEY=your-groq-api-key
```

### 3. 运行分析

```powershell
# 激活虚拟环境
.venv\Scripts\activate

# 运行单只 A 股分析（300476 = 胜宏科技）
python -m src.main --tickers 300476 --start-date 2025-09-01 --end-date 2026-05-18 --model deepseek-chat --analysts-all --html

# 分析多只股票
python -m src.main --tickers 300476,600519,000858 --model deepseek-chat --analysts-all --html

# 只使用特定代理
python -m src.main --tickers 300476 --model deepseek-chat --analysts warren_buffett,ben_graham,technical_analyst --html
```

### 4. 查看报告

运行完成后，在 `results/` 目录下会生成两个文件：

- `hedgefund_<ticker>_<timestamp>.json` — 原始 JSON 数据
- `report_<ticker>_<timestamp>.html` — 中文 HTML 可视化报告

用浏览器打开 HTML 文件即可查看完整分析报告。

## 命令行参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `--tickers` | 股票代码（逗号分隔）| `300476,600519` |
| `--start-date` | 分析起始日期 | `2025-09-01` |
| `--end-date` | 分析截止日期 | `2026-05-18` |
| `--model` | LLM 模型名称 | `deepseek-chat`、`gpt-4o` |
| `--analysts` | 指定代理（逗号分隔）| `warren_buffett,ben_graham` |
| `--analysts-all` | 使用全部代理 | — |
| `--html` | 生成 HTML 报告 | — |
| `--show-reasoning` | 显示推理过程 | — |

### 支持的模型

| 提供商 | 可用模型 |
|--------|----------|
| **DeepSeek** | `deepseek-chat`, `deepseek-reasoner` |
| **OpenAI** | `gpt-4o`, `gpt-4.1`, `o4-mini`, `o3` 等 |
| **Anthropic** | `claude-sonnet-4-20250514`, `claude-3.5-sonnet` 等 |
| **Groq** | `llama-3.3-70b`, `deepseek-r1-distill-llama-70b` 等 |
| **Google** | `gemini-2.5-flash`, `gemini-2.5-pro` 等 |
| **xAI** | `grok-3`, `grok-4` 等 |
| **Moonshot** | `kimi-k2`, `moonshot-v1-8k` 等 |
| **Ollama** | 本地模型（需加 `--ollama`） |

## HTML 报告结构

报告包含以下板块：

1. **页头**：股票代码、模型、日期范围
2. **交易决策卡片**：多/空/持有、置信度
3. **投资组合摘要**：看多/看空/中性 统计
4. **代理分析概览**：所有代理信号与核心论点表格
5. **代理详细分析**：每个代理的完整分析卡片
6. **基本面数据详情**：盈利能力、成长性、财务健康、估值
7. **增长分析详情**：历史增长、PEG、利润率、FCF 趋势
8. **新闻情绪分析**：情绪分布柱状图 + 逐条新闻详情

## 项目结构

```
ai-hedge-fund-cn/
├── src/
│   ├── main.py              # 主入口
│   ├── agents/              # 21 个代理实现
│   │   ├── warren_buffett.py
│   │   ├── ben_graham.py
│   │   ├── fundamentals.py
│   │   ├── technicals.py
│   │   ├── news_sentiment.py
│   │   └── ...
│   ├── tools/
│   │   ├── cn_data.py       # A 股数据获取（Tushare + Eastmoney + AKShare）
│   │   └── api.py           # 通用 API 工具
│   ├── utils/
│   │   ├── html_report.py   # HTML 报告生成
│   │   ├── llm.py           # LLM 调用封装
│   │   ├── analysts.py      # 代理配置
│   │   └── display.py       # 终端输出
│   ├── llm/
│   │   └── models.py        # LLM 模型配置
│   ├── graph/
│   │   └── state.py         # LangGraph 状态定义
│   ├── cli/
│   │   └── input.py         # CLI 参数解析
│   └── backtesting/         # 回测引擎
├── docker/                  # Docker 部署
├── assets/                  # 项目展示资源（如收款码）
├── results/                 # 分析结果输出
├── .env                     # 环境变量（需手动创建）
├── .env.example             # 环境变量模板
├── pyproject.toml           # Poetry 依赖配置
└── README.md
```

## Docker 部署

```bash
cd docker

# Linux/Mac
./run.sh --ticker 300476,600519 --start-date 2025-09-01 --end-date 2026-05-18 --model deepseek-chat main

# Windows
run.bat --ticker 300476,600519 --start-date 2025-09-01 --end-date 2026-05-18 --model deepseek-chat main
```

## 常见问题

### Tavily 报错 "plan's set usage limit"
非关键错误。Tavily 是国外新闻搜索 API（有免费额度限制），新闻和内幕交易数据已改用 Eastmoney/AKShare/Tushare 本地获取，不影响分析结果。

### `langchain_google_genai` 找不到
需安装 google 依赖：`pip install langchain-google-genai` 或 `poetry install`。若不使用 Gemini 模型可直接忽略。

### Tushare 数据为空
确认 `.env` 中 `TUSHARE_TOKEN` 已正确配置，且 Tushare Pro 积分 >= 2000。

### 某些指标显示 null/0.0
部分 A 股数据源（如内部人交易、FCF 增长率）取决于公司披露和 Tushare 接口覆盖度。对于无数据的情况系统会显示默认值。

---

## 支持项目

如果这个项目对你有帮助，欢迎以“请喝咖啡”的方式小额打赏，支持我继续维护 A 股数据源、分析代理和报告体验。感谢每一份鼓励！

| 微信支付 | 支付宝 |
|---------|--------|
| <img src="assets/wechat-pay.jpg" alt="微信支付收款码" width="260"> | <img src="assets/alipay.jpg" alt="支付宝收款码" width="260"> |

---

## 许可证

MIT License
