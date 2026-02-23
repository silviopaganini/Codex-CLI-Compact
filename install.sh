#!/usr/bin/env bash
# Dual-Graph one-time setup
# Usage: curl -sSL https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main/install.sh | bash

set -euo pipefail

BASE_URL="https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main"
INSTALL_DIR="$HOME/.dual-graph"
VENV="$INSTALL_DIR/venv"
mkdir -p "$INSTALL_DIR"

echo "[install] Downloading files..."
curl -sSL "$BASE_URL/graph_builder.py"    -o "$INSTALL_DIR/graph_builder.py"
curl -sSL "$BASE_URL/mcp_graph_server.py" -o "$INSTALL_DIR/mcp_graph_server.py"
curl -sSL "$BASE_URL/dg.py"               -o "$INSTALL_DIR/dg.py"
curl -sSL "$BASE_URL/dg"        -o "$INSTALL_DIR/dg"        && chmod +x "$INSTALL_DIR/dg"
curl -sSL "$BASE_URL/dgc"       -o "$INSTALL_DIR/dgc"       && chmod +x "$INSTALL_DIR/dgc"
curl -sSL "$BASE_URL/dgc-bench" -o "$INSTALL_DIR/dgc-bench" && chmod +x "$INSTALL_DIR/dgc-bench"

echo "[install] Creating Python venv at $VENV ..."
python3 -m venv "$VENV"

echo "[install] Installing Python dependencies into venv..."
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
echo "  # Codex CLI (one-time MCP registration):"
echo "  codex mcp add dual-graph --url https://codex-cli-compact-production.up.railway.app/mcp"
echo ""
echo "Then per project:"
echo "  dgc /path/to/project   # Claude Code (local, private — MCP config auto-updated)"
echo "  dg  /path/to/project   # Codex CLI   (Railway)"
