#!/bin/bash

# 啟用錯誤即刻中斷機制
set -e

# 顏色定義
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # 重設顏色

IMAGE_NAME="stock-analysis-agent"
TAG="latest"

echo -e "${BLUE}=== 🤖 開始建置 Docker 映像檔: ${IMAGE_NAME}:${TAG} ===${NC}"

# 執行 Docker Build
docker build -t "${IMAGE_NAME}:${TAG}" .

echo ""
echo -e "${GREEN}=== 🎉 Docker 映像檔建置完成！ ===${NC}"
echo -e "您可以使用以下指令來啟動 Web 服務："
echo -e "  docker run -d -p 8000:8000 --env-file .env --name stock-agent ${IMAGE_NAME}:${TAG}"
echo -e "或者是透過互動模式運行並進入 bash："
echo -e "  docker run -it --env-file .env -p 8000:8000 ${IMAGE_NAME}:${TAG} bash"
echo ""
