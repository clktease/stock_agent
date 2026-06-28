#!/bin/bash
# Script to run the MCP SSE Server inside WSL under the stock-agent conda environment

# Set path and active folder
PROJECT_DIR="/mnt/f/deep_agent"
cd "$PROJECT_DIR" || exit 1

# Try to find conda
export PATH="$HOME/anaconda3/bin:$HOME/miniconda3/bin:$PATH"
CONDA_EXE=""

if command -v conda &> /dev/null; then
    CONDA_EXE="conda"
else
    for p in "$HOME/anaconda3" "$HOME/miniconda3" "/opt/miniconda3" "/opt/anaconda3"; do
        if [ -f "$p/bin/conda" ]; then
            CONDA_EXE="$p/bin/conda"
            break
        fi
    done
fi

if [ -z "$CONDA_EXE" ]; then
    echo "❌ Error: conda was not found in WSL. Please check your conda installation."
    exit 1
fi

echo "🚀 Starting Stock Analysis MCP Server (Streamable HTTP) inside WSL conda env..."
"$CONDA_EXE" run -n stock-agent python mcp_sse_server.py
