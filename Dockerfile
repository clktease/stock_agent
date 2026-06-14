# 使用官方輕量級 Python 3.11 映像檔
FROM python:3.11-slim

# 設定環境變數，避免 Python 寫入 .pyc 檔且讓 logs 即時輸出
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# 設定工作目錄
WORKDIR /app

# 安裝基本系統工具（如 curl 可用於容器健康狀態檢查）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 複製依賴檔案以利用 Docker 快取層
COPY requirements.txt .

# 升級 pip 並安裝套件
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# 複製應用程式所有程式碼與知識庫
COPY . .

# 曝露 FastAPI 的 Port 8000
EXPOSE 8000

# 預設啟動 web_server.py
CMD ["python", "web_server.py"]
