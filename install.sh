#!/usr/bin/env bash
# Dual-Graph one-time setup
# Usage: curl -sSL https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main/install.sh | bash

set -euo pipefail

BASE_URL="https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main"
INSTALL_DIR="$HOME/.dual-graph"
VENV="$INSTALL_DIR/venv"
mkdir -p "$INSTALL_DIR"

echo "[install] Downloading core engine..."
curl -sSL "$BASE_URL/core/mcp_graph_server.py"  -o "$INSTALL_DIR/mcp_graph_server.py"
curl -sSL "$BASE_URL/core/graph_builder.py"     -o "$INSTALL_DIR/graph_builder.py"
curl -sSL "$BASE_URL/core/dual_graph_launch.sh" -o "$INSTALL_DIR/dual_graph_launch.sh" && chmod +x "$INSTALL_DIR/dual_graph_launch.sh"
curl -sSL "$BASE_URL/core/dg.py"                -o "$INSTALL_DIR/dg.py"

echo "[install] Downloading CLI tools..."
curl -sSL "$BASE_URL/bin/dgc" -o "$INSTALL_DIR/dgc" && chmod +x "$INSTALL_DIR/dgc"
curl -sSL "$BASE_URL/bin/dg"  -o "$INSTALL_DIR/dg"  && chmod +x "$INSTALL_DIR/dg"

echo "[install] Creating Python venv at $VENV ..."
python3 -m venv "$VENV"

echo "[install] Installing Python dependencies..."
"$VENV/bin/pip" install "mcp>=1.3.0" uvicorn anyio starlette --quiet

# Add to PATH if not already there
SHELL_RC="$HOME/.zshrc"
[[ "$SHELL" == */bash ]] && SHELL_RC="$HOME/.bashrc"
if ! grep -q '.dual-graph' "$SHELL_RC" 2>/dev/null; then
  echo 'export PATH="$PATH:$HOME/.dual-graph"' >> "$SHELL_RC"
  echo "[install] Added ~/.dual-graph to PATH in $SHELL_RC"
fi

echo ""
echo "[install] Done! Run once:"
echo "  source $SHELL_RC"
echo ""
echo "Then per project:"
echo "  dgc /path/to/project   # Claude Code (local MCP, fully private)"
echo "  dg  /path/to/project   # Codex CLI   (local MCP, fully private)"
