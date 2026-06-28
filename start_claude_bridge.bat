@echo off
chcp 65001 >nul
title Claude.ai MCP Bridge Control Panel

echo =================================================================
echo   📈 Claude.ai MCP Bridge 自動化啟動工具
echo   此工具會自動偵測 WSL IP、啟動 MCP 伺服器，並開啟 Cloudflare 穿透。
echo =================================================================
echo.

:: 1. 偵測 WSL 的 IP 位置
echo 🔍 偵測 WSL 網路中...
for /f "tokens=1" %%i in ('wsl -d Ubuntu-20.04 -- hostname -I') do set WSL_IP=%%i

if "%WSL_IP%"=="" (
    echo ❌ 錯誤：無法取得 WSL IP，請確認 WSL 是否正常運行。
    pause
    exit /b
)
echo 🔗 偵測到 WSL IP: %WSL_IP%
echo.

:: 2. 在獨立的新視窗啟動 WSL MCP 伺服器
echo 🚀 正在啟動 WSL MCP 伺服器 (Port 8001)...
start "MCP Server (WSL)" wsl -d Ubuntu-20.04 -- bash /mnt/f/deep_agent/run_mcp_wsl.sh
timeout /t 3 >nul

:: 3. 在本視窗啟動 Cloudflare Tunnel，方便使用者複製產生的公開網址
echo 🌐 正在啟動 Cloudflare Tunnel 指向 http://%WSL_IP%:8001 ...
echo =================================================================
echo   💡 啟動成功後，請在下方尋找：
echo   Your quick Tunnel has been created! Visit it at:
echo   https://xxxx.trycloudflare.com
echo.
echo   請複製該網址並在尾端加上 "/mcp" 填入 Claude.ai Custom Connector！
echo   例如：https://xxxx.trycloudflare.com/mcp
echo =================================================================
echo.

F:\stock_agent\cloudflared.exe tunnel --url http://%WSL_IP%:8001

pause
