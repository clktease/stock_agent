# Stock Analysis Deep Agent

一個基於 **LangChain Deep Agents** 框架打造的 AI 股票分析助手，整合 **MCP (Model Context Protocol)** 和自定義 **Skills**，可進行技術分析、基本面分析、選股篩選和投資組合評估。

## 🏗️ 架構

```
┌─────────────────────────────────────────────────────────────────┐
│              📊 Stock Analysis Deep Agent (主控 Agent)           │
│              (規劃、協調、整合所有分析結果)                          │
│                                                                 │
│  ┌─────────────────┐  ┌─────────────────┐  ┌───────────────┐   │
│  │ Technical       │  │ Fundamental     │  │ News &        │   │
│  │ Analyst         │  │ Analyst         │  │ Sentiment     │   │
│  │ Sub-agent       │  │ Sub-agent       │  │ Sub-agent     │   │
│  └─────────────────┘  └─────────────────┘  └───────────────┘   │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                Portfolio Manager Sub-agent                 │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
         ↕
┌────────────────────────────────────────────────────────────────┐
│                   MCP Server (stock-analysis-mcp)              │
│   Direct skills: Price | Technical | Fundamental | Portfolio   │
└────────────────────────────────────────────────────────────────┘
         ↕
    Yahoo Finance API (免費, 無需API Key)
```

## 📁 檔案結構

```
deep_agent/
├── agent.py          # 主要入口點 – Deep Agent 主控程式
├── skills.py         # 自定義 Skills (LangChain Tools)
├── mcp_server.py     # MCP 伺服器 – 暴露 skills 作為 MCP 工具
├── mcp_config.json   # MCP 伺服器設定
├── test_skills.py    # Skills 測試套件
├── requirements.txt  # Python 相依套件
├── .env.example      # 環境變數範例
└── README.md         # 說明文件
```

## 🛠️ Skills (技能/工具)

| Skill | 描述 |
|-------|------|
| `get_stock_price` | 即時股價、OHLCV 歷史資料、基本統計 |
| `calculate_technical_indicators` | SMA/EMA、RSI、MACD、布林通道、ATR、成交量趨勢 |
| `get_fundamental_data` | P/E、P/B、獲利率、ROE、殖利率、分析師評級 |
| `screen_stocks` | 依市值、P/E、殖利率、產業篩選股票 |
| `compare_stocks` | 多股票並排比較績效與估值 |
| `calculate_portfolio_metrics` | 投資組合報酬、波動率、Sharpe Ratio、最大回撤 |

## 🤖 Sub-agents (子代理)

| Sub-agent | 職責 |
|-----------|------|
| `technical-analyst` | 技術分析專家 – 價格走勢、指標訊號 |
| `fundamental-analyst` | 基本面專家 – 財報、估值、競爭優勢 |
| `news-sentiment-analyst` | 新聞與情緒分析 – 催化劑、風險事件 |
| `portfolio-manager` | 投資組合管理 – 風險調整後報酬、配置建議 |

## 🚀 快速開始

### 1. 安裝相依套件

```bash
pip install -r requirements.txt
```

### 2. 設定環境變數

```bash
# Windows
copy .env.example .env

# Linux/Mac
cp .env.example .env
```

編輯 `.env` 填入你的 API Key：
```env
OPENAI_API_KEY=sk-...
TAVILY_API_KEY=tvly-...   # 可選，用於新聞搜尋
```

### 3. 測試 Skills

```bash
python test_skills.py
```

### 4. 啟動 Agent

```bash
# 互動式模式
python agent.py

# 單次查詢模式
python agent.py --query "分析 AAPL 的技術面與基本面"

# 同時啟用 MCP 伺服器
python agent.py --with-mcp
```

## 💬 使用範例

```
# 單股完整分析
Analyze AAPL with full technical and fundamental analysis

# 多股比較
Compare NVDA, AMD, and INTC over the past year

# 選股篩選
Screen stocks with P/E < 20 from: AAPL,MSFT,GOOGL,META,AMZN

# 投資組合分析
Calculate portfolio metrics for AAPL 40%, MSFT 30%, GOOGL 30%

# 技術指標查詢
What is the RSI and MACD for TSLA?

# 市場總覽
Show me the market overview for today

# 台股 (台積電)
分析 2330.TW 的技術面
```

## 🔌 MCP 整合

### 作為 MCP Server 使用

你可以將 `mcp_server.py` 掛接到任何 MCP 相容客戶端（Claude Desktop、Cursor 等）：

```json
// claude_desktop_config.json
{
  "mcpServers": {
    "stock-analysis": {
      "command": "python",
      "args": ["/path/to/deep_agent/mcp_server.py"]
    }
  }
}
```

### 連接外部 MCP Server

在 `agent.py` 的 `load_mcp_tools_async()` 中加入更多伺服器：

```python
client = MultiServerMCPClient({
    "alphavantage": {
        "url": "https://mcp.alphavantage.co/mcp?apikey=YOUR_KEY",
        "transport": "sse",
    },
    "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "./reports"],
    },
})
```

## 🧠 LLM 支援

| Provider | 模型建議 |
|----------|----------|
| OpenAI | `openai:gpt-4o` (主控) / `openai:gpt-4o-mini` (子代理) |
| Anthropic | `anthropic:claude-3-5-sonnet-20241022` |

在 `.env` 中設定：
```env
AGENT_MODEL=openai:gpt-4o
SUBAGENT_MODEL=openai:gpt-4o-mini
```

## ⚠️ 免責聲明

本工具僅供**教育與研究目的**。所有分析結果不構成個人投資建議。投資有風險，請自行判斷並諮詢專業財務顧問。

## 📦 主要相依套件

- `deepagents` – LangChain Deep Agents 框架
- `langchain-mcp-adapters` – MCP 整合層
- `mcp` – Model Context Protocol SDK
- `yfinance` – Yahoo Finance 股票資料
- `pandas`, `numpy` – 資料處理
- `ta` – 技術分析指標庫
- `tavily-python` – 網路新聞搜尋（可選）
- `rich` – 美化終端輸出
