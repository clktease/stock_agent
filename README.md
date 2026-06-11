# Stock Analysis Deep Agent

一個基於 **LangChain Deep Agents** 框架打造的 AI 股票分析助手，整合了 **MCP (Model Context Protocol)**、自定義 **Skills** 與 **RAG (Retrieval-Augmented Generation)**。系統支援強大的 Web UI 視覺化介面，即時追蹤工具呼叫路徑，並提供 Session 記憶與對話歷史管理功能。

## 🏗️ 架構

```
                                  ┌──────────────────┐
                                  │    Web Browser   │ (static/index.html)
                                  └────────┬─────────┘
                                           │ WebSocket
                                  ┌────────▼─────────┐
                                  │  FastAPI Server  │ (web_server.py)
                                  └────────┬─────────┘
                                           │
                    ┌──────────────────────┴──────────────────────┐
                    │          📊 Stock Analysis Deep Agent       │ (agent.py)
                    │         (主控 Orchestrator & 規劃代理)       │
                    └──────────────────────┬──────────────────────┘
                                           │
         ┌───────────────────┬─────────────┴───────┬───────────────────┐
         ▼                   ▼                     ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│    Technical    │ │   Fundamental   │ │      News &     │ │    Portfolio    │
│    Analyst      │ │    Analyst      │ │    Sentiment    │ │    Manager      │
│   Sub-agent     │ │   Sub-agent     │ │    Sub-agent    │ │   Sub-agent     │
└────────┬────────┘ └────────┬────────┘ └────────┬────────┘ └────────┬────────┘
         │                   │                   │                   │
         ▼                   ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│     SKILL       │ │     MCP Tool    │ │    RAG Tool     │ │     SKILL       │
│  (get_price...) │ │  (FRED/EDGAR...)│ │ (FAISS Search)  │ │ (portfolio...)  │
└─────────────────┘ └─────────────────┘ └─────────────────┘ └─────────────────┘
```

## 📁 檔案結構

```
deep_agent/
├── agent.py          # 主要入口點 – Deep Agent 主控與協調程式
├── skills.py         # 自定義 Skills (LangChain Tools)
├── mcp_server.py     # MCP 伺服器 – 暴露 skills 作為 MCP 工具
├── mcp_config.json   # MCP 伺服器設定
├── rag_tools.py      # RAG 工具 – 載入知識庫並建立 FAISS 向量資料庫
├── web_server.py     # FastAPI Web 伺服器 (包含 WebSocket 與 Session 記憶管理)
├── static/
│   └── index.html    # Demo UI 介面 (純 HTML+CSS+JS, 包含 Session ID 與 Live Tool Tracker)
├── knowledge_base/   # RAG 知識庫 (投資框架與市場歷史等 Markdown 檔案)
├── vector_store/     # FAISS 向量資料庫索引存儲
├── test_skills.py    # Skills 測試套件
├── test_mcp_rag.py   # MCP & RAG 整合測試
├── requirements.txt  # Python 相依套件
├── .env.example      # 環境變數範例
└── README.md         # 說明文件
```

## 🛠️ 工具路由分類 (Skills / MCP / RAG)

系統將工具呼叫分為三大路由類型，並於 UI 中以不同顏色標籤區分：

### 1. 🟦 SKILL (自定義本地工具)
* `get_stock_price`: 獲取即時股價、OHLCV 歷史資料、基本統計資訊。
* `calculate_technical_indicators`: 計算 SMA/EMA、RSI、MACD、布林通道、ATR 等技術指標。
* `get_fundamental_data`: 查詢 P/E、P/B、獲利率、ROE、殖利率、分析師評級。
* `screen_stocks`: 依市值、P/E、殖利率、產業篩選股票。
* `compare_stocks`: 多股票並排比較績效與估值。
* `calculate_portfolio_metrics`: 投資組合報酬、波動率、Sharpe Ratio、最大回撤。

### 🟧 MCP (Model Context Protocol 外部工具)
* `get_economic_indicators`: 查詢美國聯準會利率、CPI、GDP 成長率、失業率等總經數據 (透過 FRED API)。
* `get_sec_filing_summary`: 查詢並總結 Apple 等上市公司的最新 10-K 或 10-Q 申報文件。
* `get_market_overview`: 查詢今日市場大盤表現概覽。

### 🟪 RAG (知識庫檢送工具)
* `search_investment_knowledge`: 檢索經典投資框架 (如價值投資、成長投資、技術分析指引、現代投資組合理論)。
* `search_market_history`: 檢索重大歷史市場事件的背景與教訓 (如 2000 年網路泡沫、2008 年金融海嘯、2020 年新冠疫情崩盤、2022 年升息熊市)。

---

## 🤖 Sub-agents (子代理)

主控 Agent 會根據查詢需求，指派給特定的專業子代理：
* `technical-analyst` (技術分析專家): 專門分析價格走勢與指標。
* `fundamental-analyst` (基本面專家): 專門分析財報與公司估值。
* `news-sentiment-analyst` (新聞輿情專家): 專門搜集新聞、總經指標與市場情緒。
* `portfolio-manager` (投資組合管理): 專門進行風險評估與資產配置建議。

---

## 🚀 快速開始

### 1. 安裝相依套件

```bash
pip install -r requirements.txt
```

### 2. 設定環境變數

複製 `.env.example` 為 `.env`，並填入你的 API Key：
```env
OPENAI_API_KEY=sk-...
TAVILY_API_KEY=tvly-...      # 可選，用於新聞搜尋
FRED_API_KEY=your_fred_key   # 可選，用於總經數據
```

### 3. 測試環境與工具

```bash
# 測試 RAG 知識庫與向量資料庫建立
python test_mcp_rag.py

# 測試 Skills 工具運作
python test_skills.py
```

### 4. 啟動 Web UI 進行展示

```bash
# 啟動 FastAPI 伺服器
python web_server.py
```

啟動後，使用瀏覽器打開 **`http://localhost:8000`** 即可進入 Demo 介面！

---

## 💻 Web UI 介面特色

1. **三欄暗色玻璃擬態佈局**：
   - **左欄 (範例查詢)**: 預設 16 個涵蓋 SKILL、MCP、RAG 以及混合路徑的範例查詢，點擊即可一鍵輸入。
   - **中欄 (聊天主區)**: 包含美麗的歡迎卡片、聊天氣泡、支援完整 Markdown 與表格渲染的回答，以及對話完成後的耗時與工具統計。
   - **右欄 (Live Tool Tracker)**: 即時以時間軸動畫呈現主控 Agent 如何調度子代理，以及子代理如何呼叫 SKILL/MCP/RAG 工具。
2. **Session 記憶與對話歷史**：
   - **Session ID 標籤**: 頂部即時顯示當前 Session 的 ID。
   - **對話輪數徽章**: 顯示目前 Session 已累積的歷史對話輪數。
   - **✦ New Chat 按鈕**: 點擊可清除當前畫面與記憶，向後端發送請求重置對話歷史。

---

## 🧠 LLM 設定 (GPT-5.2)

預設採用最新的 **OpenAI GPT-5.2** 模型作為主控與子代理。你可以在 `.env` 中設定：

```env
# ---- Model Selection ----
AGENT_MODEL=openai:gpt-5.2
SUBAGENT_MODEL=openai:gpt-5.2
```

---

## ⚠️ 免責聲明

本工具僅供**教育與研究目的**。所有分析結果不構成個人投資建議。投資有風險，請自行判斷並諮詢專業財務顧問。
