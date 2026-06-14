#!/bin/bash

# 啟用錯誤即刻中斷機制
set -e

# 顏色定義
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # 重設顏色

IMAGE_NAME="stock-analysis-agent"
TAG="latest"

# 1. 檢查 Docker 映像檔是否存在，若不存在則引導/自動建置
if ! docker image inspect "${IMAGE_NAME}:${TAG}" >/dev/null 2>&1; then
    echo -e "${YELLOW}提示: 找不到 Docker 映像檔 ${IMAGE_NAME}:${TAG}，即將為您自動進行建置...${NC}"
    chmod +x build.sh
    ./build.sh
fi

# 2. 判斷是否需要載入 .env 檔案
ENV_FILE_PARAM=""
if [ -f .env ]; then
    ENV_FILE_PARAM="--env-file .env"
    echo -e "${BLUE}ℹ 已偵測到 .env 檔案，將自動載入環境變數以進行測試。${NC}"
else
    echo -e "${YELLOW}⚠ 警告: 找不到本地 .env 檔案。如果測試失敗，可能是因為缺少 API 金鑰。${NC}"
    echo -e "${YELLOW}如需設定，請複製 .env.example 並重新命名為 .env 填入金鑰，或直接在環境中 export 金鑰。${NC}"
fi

echo -e "\n${BLUE}=== 🧪 開始在 Docker 容器內執行整合測試 ===${NC}"

# 執行套件載入測試
echo -e "\n${BLUE}[測試 1/3] 驗證環境套件導入 (test_imports.py)...${NC}"
docker run --rm $ENV_FILE_PARAM "${IMAGE_NAME}:${TAG}" python test_imports.py

# 執行 Skills 功能測試
echo -e "\n${BLUE}[測試 2/3] 驗證 Skills 自定義工具 (test_skills.py)...${NC}"
docker run --rm $ENV_FILE_PARAM "${IMAGE_NAME}:${TAG}" python test_skills.py

# 執行 MCP + RAG 測試
echo -e "\n${BLUE}[測試 3/3] 驗證 MCP 與 RAG 功能 (test_mcp_rag.py)...${NC}"
docker run --rm $ENV_FILE_PARAM "${IMAGE_NAME}:${TAG}" python test_mcp_rag.py

echo ""
echo -e "${GREEN}=== 🎉 所有 Docker 容器測試皆已成功通過！ ===${NC}"
echo ""
